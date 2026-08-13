"""会话循环测试：假图 + 临时记忆，测循环四动作（读 recent → 注入 → invoke → 写回两轮）

记忆隔离由 conftest 自动夹具提供（MEMORY_PATH 指向 tmp）。
"""

import pytest

from xiao_wen import memory as memory_store
from xiao_wen.session import ChatResult, chat


class FakeGraph:
    def __init__(self, answer="答", intent="其他", reason="测试"):
        self.answer = answer
        self.intent = intent
        self.reason = reason
        self.calls = []

    def invoke(self, state):
        self.calls.append(state)
        return {"answer": self.answer, "intent": self.intent, "reason": self.reason}


def test_chat_loop_four_actions():
    """读 recent → 注入 → invoke → 写回两轮"""
    graph = FakeGraph()
    memory_store.add_message("user", "上一轮")
    memory_store.add_message("assistant", "上一轮回答")

    r = chat("新问题", graph=graph)

    assert isinstance(r, ChatResult)
    assert r.answer == "答" and r.intent == "其他" and r.reason == "测试"
    # 注入的 recent 包含历史
    assert "上一轮" in graph.calls[0]["recent"]
    assert graph.calls[0]["user_input"] == "新问题"
    # 写回两轮
    msgs = memory_store.get_recent_messages(6)
    assert [m["role"] for m in msgs[-2:]] == ["user", "assistant"]
    assert [m["content"] for m in msgs[-2:]] == ["新问题", "答"]


def test_chat_propagates_exceptions():
    class BoomGraph:
        def invoke(self, state):
            raise RuntimeError("LLM 挂了")

    with pytest.raises(RuntimeError, match="LLM 挂了"):
        chat("x", graph=BoomGraph())


def test_chat_uses_injected_store():
    calls = []

    class FakeStore:
        def format_recent_messages(self, n, *, session_id="default"):
            return "无历史"

        def add_message(self, role, content, *, session_id="default"):
            calls.append((role, content, session_id))

    graph = FakeGraph()
    r = chat("hi", session_id="会话A", graph=graph, store=FakeStore())
    assert r.answer == "答"
    assert calls == [("user", "hi", "会话A"), ("assistant", "答", "会话A")]
    assert graph.calls[0]["recent"] == "无历史"


def test_chat_default_graph_is_parallel_supervisor(monkeypatch):
    """默认图 = 图工厂的调度图（parallel=True）：产品 hot path 并行能力接线（Q1/Q6a）"""
    import xiao_wen.graph_builder as gb

    seen = {}

    class FakeGraph:
        def invoke(self, state):
            seen["state"] = state
            return {"answer": "答", "intent": "其他", "reason": "默认图"}

    def fake_build(parallel=False):
        seen["parallel"] = parallel
        return FakeGraph()

    monkeypatch.setattr(gb, "build_supervisor_graph", fake_build)
    r = chat("hi")
    assert r.answer == "答"
    assert seen["parallel"] is True, "默认图应为调度图（多意图并行）"
    assert seen["state"]["recent"] is not None


def test_chat_session_isolation_with_fake_graph():
    """会话隔离验收（无 LLM）：A 写记忆 → B 读不到；State 携带 session_id 到图"""
    from xiao_wen import memory as memory_store

    captured = {}

    class RecGraph:
        def invoke(self, state):
            captured["session_id"] = state.get("session_id")
            captured["recent"] = state["recent"]
            return {"answer": "答", "intent": "其他", "reason": "测试"}

    chat("A的第一个问题", session_id="会话A", graph=RecGraph())
    chat("A的第二个问题", session_id="会话A", graph=RecGraph())
    chat("B的问题", session_id="会话B", graph=RecGraph())

    # State 携带 session_id（产品路径：图内 agent 可感知会话）
    assert captured["session_id"] == "会话B"
    # A 的记忆有 A 的两轮（2 轮 × 用户/助手 2 条）；B 只有 B 自己的
    msgs_a = memory_store.get_recent_messages(6, session_id="会话A")
    msgs_b = memory_store.get_recent_messages(6, session_id="会话B")
    assert [m["content"] for m in msgs_a] == ["A的第一个问题", "答", "A的第二个问题", "答"]
    assert [m["content"] for m in msgs_b] == ["B的问题", "答"]
    assert memory_store.get_recent_messages(6, session_id="default") == []


def test_agents_use_state_session_id(monkeypatch):
    """preference/history agent 从 State 取 session_id 写入对应会话（无 LLM：短路模型）"""
    from xiao_wen.agents import history_agent, preference_agent
    from xiao_wen.memory import get_preferences

    recs = preference_agent.PreferenceList(
        records=[preference_agent.PreferenceRecord(category="常驻城市", content="上海", is_update=True)]
    )

    def _fake_pref_model():
        class M:
            def invoke(self, _):
                return recs

        return M()

    monkeypatch.setattr(preference_agent, "_pref_model", _fake_pref_model)
    out = preference_agent.run({"user_input": "我现在常住上海", "session_id": "会话A"})
    assert "上海" in out["answer"]
    assert [p["content"] for p in get_preferences("常驻城市", session_id="会话A")] == ["上海"]
    assert get_preferences("常驻城市", session_id="会话B") == []

    # history agent：从 State 取 session_id 传给 get_itineraries
    seen = {}

    def fake_get_itineraries(*args, **kwargs):
        seen["session_id"] = kwargs.get("session_id")
        return [
            {
                "to_city": "北京",
                "from_city": "上海",
                "start_date": "2026-10-08",
                "duration_days": 4,
                "summary": "北京出差",
            }
        ]

    monkeypatch.setattr(history_agent, "get_itineraries", fake_get_itineraries)
    out = history_agent.run({"session_id": "会话B"})
    assert seen["session_id"] == "会话B"
    assert "北京" in out["answer"]


def test_preference_agent_records_multiple_preferences(monkeypatch):
    """偏好 agent：一条消息含多个偏好 → 全部写入（如「我喜欢住汉庭，常住上海」→ 住宿 + 常驻城市）"""
    from xiao_wen.agents import preference_agent
    from xiao_wen.memory import get_preferences

    recs = preference_agent.PreferenceList(
        records=[
            preference_agent.PreferenceRecord(category="住宿", content="喜欢住汉庭", is_update=False),
            preference_agent.PreferenceRecord(category="常驻城市", content="上海", is_update=True),
        ]
    )

    def _fake_pref_model():
        class M:
            def invoke(self, _):
                return recs

        return M()

    monkeypatch.setattr(preference_agent, "_pref_model", _fake_pref_model)
    out = preference_agent.run({"user_input": "我喜欢住汉庭，常住上海", "session_id": "会话A"})
    assert "住宿" in out["answer"] and "常驻城市" in out["answer"]
    prefs = get_preferences(session_id="会话A")
    assert {p["category"] for p in prefs} == {"住宿", "常驻城市"}
    assert [p["content"] for p in prefs if p["category"] == "常驻城市"] == ["上海"]


def test_itinerary_agent_passes_session_to_trip_planner(monkeypatch):
    """行程 agent：State 的 session_id 贯穿到 trip_planner 的 add_itinerary（无 LLM：短路模型链）"""
    from xiao_wen import trip_planner
    from xiao_wen.agents import itinerary_agent

    captured = {}

    def fake_add_itinerary(facts, summary, *, session_id="default"):
        captured["session_id"] = session_id
        captured["summary"] = summary
        return {"summary": summary, "ts": "t"}

    monkeypatch.setattr(trip_planner, "add_itinerary", fake_add_itinerary)
    req = trip_planner.TripRequest(
        from_city="上海", to_city="北京", start_date="2026-10-08", duration_days=4, hotel_pref="无", budget_pref="中等"
    )
    plan = trip_planner.ItineraryPlan(
        days=[],
        summary="北京出差 4 天",
        reasons=["靠近会场"],
    )

    class FakeExtract:
        def invoke(self, _):
            return req

    class FakePlan:
        def invoke(self, _):
            return plan

    monkeypatch.setattr(trip_planner, "_extract_model", FakeExtract)
    monkeypatch.setattr(trip_planner, "_plan_model", FakePlan)

    out = itinerary_agent.run({"user_input": "我10月8日去北京开会4天", "session_id": "会话A"})
    assert captured["session_id"] == "会话A"  # 行程写进 A 会话
    assert captured["summary"] == "北京出差 4 天"
    assert "北京" in out["answer"]


def test_itinerary_agent_appends_weather_reminder(monkeypatch):
    """行程 agent：生成成功且日期可查 → 答案附加目的地天气提醒（结合行程规划）；天气失败不影响主答案"""
    from xiao_wen import trip_planner
    from xiao_wen.agents import itinerary_agent

    req = trip_planner.TripRequest(
        from_city="上海", to_city="北京", start_date="2026-10-08", duration_days=4, hotel_pref="无", budget_pref="中等"
    )
    plan = trip_planner.ItineraryPlan(days=[], summary="北京出差 4 天", reasons=["靠近会场"])

    class FakeExtract:
        def invoke(self, _):
            return req

    class FakePlan:
        def invoke(self, _):
            return plan

    monkeypatch.setattr(trip_planner, "_extract_model", FakeExtract)
    monkeypatch.setattr(trip_planner, "_plan_model", FakePlan)
    monkeypatch.setattr(
        trip_planner, "add_itinerary", lambda facts, summary, *, session_id="default": {"summary": summary}
    )

    class FakeWeather:
        def invoke(self, args):
            return f"{args['city']} {args['date']} 晴 25°C"

    monkeypatch.setattr(itinerary_agent, "get_weather", FakeWeather())
    out = itinerary_agent.run({"user_input": "10月8日去北京开会4天", "session_id": "会话A"})
    assert "北京出差 4 天" in out["answer"]
    assert "目的地天气提醒" in out["answer"] and "晴" in out["answer"]

    # 天气查询失败（网络/超期）：行程主答案不受影响
    def boom(args):
        raise RuntimeError("网络挂了")

    monkeypatch.setattr(itinerary_agent, "get_weather", boom)
    out2 = itinerary_agent.run({"user_input": "10月8日去北京开会4天", "session_id": "会话A"})
    assert "北京出差 4 天" in out2["answer"]
    assert "目的地天气提醒" not in out2["answer"]


def test_itinerary_agent_confirms_vague_date(monkeypatch):
    """行程 agent：日期表达模糊（如只说了「下周」）→ 生成后明确提示日期是推断的、可调整；具体日期则无提示"""
    from xiao_wen import trip_planner
    from xiao_wen.agents import itinerary_agent

    def run_with(req):
        plan = trip_planner.ItineraryPlan(days=[], summary="杭州出差 3 天", reasons=[])

        class FakeExtract:
            def invoke(self, _):
                return req

        class FakePlan:
            def invoke(self, _):
                return plan

        monkeypatch.setattr(trip_planner, "_extract_model", FakeExtract)
        monkeypatch.setattr(trip_planner, "_plan_model", FakePlan)
        monkeypatch.setattr(
            trip_planner, "add_itinerary", lambda facts, summary, *, session_id="default": {"summary": summary}
        )
        monkeypatch.setattr(itinerary_agent, "get_weather", type("W", (), {"invoke": lambda self, a: "晴"})())
        return itinerary_agent.run({"user_input": "x", "session_id": "会话A"})["answer"]

    vague = trip_planner.TripRequest(
        from_city="北京", to_city="杭州", start_date="2026-08-17", duration_days=3, hotel_pref="无", budget_pref="中等",
        date_is_vague=True,
    )
    out_vague = run_with(vague)
    assert "按 2026-08-17 开始安排" in out_vague and "重新排" in out_vague

    exact = trip_planner.TripRequest(
        from_city="北京", to_city="杭州", start_date="2026-08-17", duration_days=3, hotel_pref="无", budget_pref="中等"
    )
    out_exact = run_with(exact)
    assert "重新排" not in out_exact


def test_preference_agent_skips_questions_no_garbage(monkeypatch):
    """疑问句（「我常住哪里」）→ 提取器返回空 records → 不写任何记忆、给引导提示"""
    from xiao_wen.agents import preference_agent
    from xiao_wen.memory import get_preferences

    recs = preference_agent.PreferenceList(records=[])

    def _empty_model():
        class M:
            def invoke(self, _):
                return recs

        return M()

    monkeypatch.setattr(preference_agent, "_pref_model", _empty_model)
    out = preference_agent.run({"user_input": "我常住哪里", "session_id": "会话C"})
    assert "询问" in out["answer"]
    assert get_preferences(session_id="会话C") == [], "疑问句绝不能写进长期记忆"


def test_history_agent_shows_preferences(monkeypatch):
    """记忆查询（如「我常住哪里」）→ 历史查询 Agent 输出记忆偏好（含常驻城市）"""
    from xiao_wen.agents import history_agent
    from xiao_wen.memory import add_or_update_preference

    add_or_update_preference("常驻城市", "上海", True, session_id="会话D")
    out = history_agent.run({"session_id": "会话D"})
    assert "常驻城市 上海" in out["answer"]
