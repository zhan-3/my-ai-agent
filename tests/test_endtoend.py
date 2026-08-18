"""真实产品接缝 smoke：只断言结构化 outcome、持久化状态与证据，不锁定模型措辞。

本文件验证真实 LLM、Embedding、主管 Agent Loop 和 Postgres 能共同完成少量关键闭环；
只断言稳定 outcome，不冻结模型的中间决策文本。
"""

from datetime import date, timedelta

import pytest

from xiao_wen import memory
from xiao_wen.session import chat


def _future_date(offset_days: int = 45) -> tuple[date, str]:
    target = date.today() + timedelta(days=offset_days)
    return target, f"{target.year}年{target.month}月{target.day}日"


def _memory_state(session_id: str) -> dict:
    return {
        "itineraries": memory.get_itineraries(session_id=session_id),
        "preferences": memory.get_preferences(session_id=session_id),
    }


@pytest.mark.integration
def test_preference_plan_history_outcomes():
    """真实模型抽取偏好和行程；验收以结构化结果与落库状态为准。"""
    session_id = "integration-memory-plan"
    preference_result = chat("我常住上海，出差不吃辣", session_id=session_id)
    assert preference_result.intent == "偏好记录"
    preferences = _memory_state(session_id)["preferences"]
    assert any(item["content"] == "上海" for item in preferences)
    assert any("辣" in item["content"] for item in preferences)

    target, target_text = _future_date()
    plan_result = chat(f"{target_text}去北京开会4天", session_id=session_id)
    assert plan_result.intent == "行程规划"
    assert plan_result.failure is None
    assert plan_result.plan is not None
    assert len(plan_result.plan.days) == 4
    assert plan_result.plan.days[0].date == target.isoformat()
    itineraries = _memory_state(session_id)["itineraries"]
    assert any(
        item["from_city"] == "上海" and item["to_city"] == "北京" and item["start_date"] == target.isoformat()
        for item in itineraries
    )

    history_result = chat("我已规划的行程是什么", session_id=session_id)
    assert history_result.intent == "历史查询"
    assert history_result.history is not None
    assert history_result.history.direction == "计划"
    assert any(item.to_city == "北京" for item in history_result.history.itineraries)


@pytest.mark.integration
def test_external_agent_returns_structured_stats():
    """真实主管发现并派发外部 Agent；验收结构化 stats，不锁定空态文案。"""
    result = chat("统计一下我的出差情况", session_id="integration-stats")
    assert result.intent == "差旅统计"
    assert result.failure is None
    assert result.stats is not None
    assert result.stats.has_data is False


@pytest.mark.integration
def test_loop_observes_history_then_stats_outcomes():
    """真实主管可依次调用两个子 Agent，并保留两个结构化 observation。"""
    session_id = "integration-parallel"
    past = date.today() - timedelta(days=30)
    memory.add_itinerary(
        {
            "from_city": "上海",
            "to_city": "北京",
            "start_date": past.isoformat(),
            "duration_days": 2,
        },
        "上海到北京出差",
        session_id=session_id,
    )
    result = chat("我上次的行程是什么，顺便统计一下出差次数", session_id=session_id)
    assert result.intent == "差旅统计"
    assert result.failure is None
    assert result.history is not None and result.history.itineraries
    assert result.stats is not None and result.stats.trips == 1


@pytest.mark.integration
def test_policy_qa_returns_grounded_evidence():
    """真实 RAG 回答必须携带同轮证据；不以是否出现某个关键词代替 grounding。"""
    result = chat("出差住宿标准是什么", session_id="integration-policy")
    assert result.intent == "知识问答"
    assert result.failure is None
    assert result.policy_status == "grounded"
    assert result.sources
    assert all(source.evidence_id and source.source for source in result.sources)


@pytest.mark.integration
def test_pending_followup_persists_both_preference_and_plan():
    """追问后的常驻城市陈述同时补全行程并保存偏好，最终 outcome 落库。"""
    session_id = "integration-pending"
    target, target_text = _future_date(60)
    first = chat(f"帮我规划{target_text}去北京的行程", session_id=session_id)
    assert first.intent == "行程规划"
    assert first.plan is None

    followup = chat("我现在常住上海", session_id=session_id)
    assert followup.intent == "行程规划"
    assert any(item["content"] == "上海" for item in _memory_state(session_id)["preferences"])

    final = chat("4天", session_id=session_id)
    assert final.intent == "行程规划"
    assert final.plan is not None and len(final.plan.days) == 4
    assert final.plan.days[0].date == target.isoformat()
    assert any(
        item["from_city"] == "上海" and item["to_city"] == "北京" for item in _memory_state(session_id)["itineraries"]
    )


@pytest.mark.integration
def test_jump_dialogue_interrupts_and_resumes_pending_trip():
    """独立偏好插入不覆盖待补行程；后续补槽仍只恢复原行程任务。"""
    user_id = "integration-jump"
    thread_id = f"{user_id}:thread-a"
    target, target_text = _future_date(65)

    first = chat(f"帮我规划{target_text}去北京的行程", thread_id, user_id=user_id)
    assert first.intent == "行程规划" and first.plan is None
    assert memory.get_active_task(thread_id=thread_id, user_id=user_id) is not None

    interruption = chat("我不吃辣", thread_id, user_id=user_id)
    assert interruption.intent == "偏好记录"
    assert "刚才的行程仍保留" in interruption.answer
    assert any("辣" in item["content"] for item in memory.get_preferences(session_id=user_id))

    home = chat("我现在常住上海", thread_id, user_id=user_id)
    assert home.intent == "行程规划" and home.plan is None
    final = chat("4天", thread_id, user_id=user_id)
    assert final.intent == "行程规划"
    assert final.plan is not None and final.plan.days[0].date == target.isoformat()
    assert memory.get_active_task(thread_id=thread_id, user_id=user_id) is None


@pytest.mark.integration
@pytest.mark.external_live
def test_weather_live_dependency_is_explicit():
    """第三方天气只做独立诊断；成功或明确失败均可，不能返回空答案。"""
    result = chat("北京明天天气怎么样", session_id="integration-weather-live")
    assert result.intent == "联网查询"
    assert result.answer.strip()
    assert result.failure is None
