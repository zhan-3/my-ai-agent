"""偏好记录子 Agent 确定性测试：偏好提取 → 延迟写 / 直接写、空记录、取消。

覆盖 run() 主路径：
  1. defer 写（对话流）→ memory_writes 延迟写清单 + 话术
  2. is_update=True → 标记覆盖（content 保否定词）
  3. 多记录（一条消息多个偏好）→ 多条写入
  4. 空记录（疑问句/非偏好陈述）→ 询问话术、零写入
  5. 直接写（非 defer）→ 真实调 memory.add_or_update_preference
  6. 请求取消 → 抛 RuntimeError（不写不完整结果）
"""

import pytest

from xiao_wen.agents import preference_agent
from xiao_wen.agents.preference_agent import PreferenceList, PreferenceRecord


def _prefs(*records: PreferenceRecord) -> PreferenceList:
    return PreferenceList(records=list(records))


def test_deferred_write_collects_memory_writes(monkeypatch):
    """路径 1：_defer_writes=True → memory_writes 延迟清单（不直接写库）。"""
    monkeypatch.setattr(
        preference_agent,
        "_invoke_pref_model",
        lambda text: _prefs(PreferenceRecord(category="住宿", content="喜欢安静", is_update=False)),
    )
    result = preference_agent.run({"user_input": "我不吃辣，住宿喜欢安静", "user_id": "u1", "_defer_writes": True})
    assert result["memory_writes"] == [
        {"type": "preference", "category": "住宿", "content": "喜欢安静", "is_update": False}
    ]
    assert "已新增偏好：住宿｜喜欢安静" in result["answer"]


def test_is_update_marks_override_and_keeps_negation(monkeypatch):
    """路径 2：更新语气 → is_update=True；content 保留否定词「不」。"""
    monkeypatch.setattr(
        preference_agent,
        "_invoke_pref_model",
        lambda text: _prefs(
            PreferenceRecord(category="餐饮", content="吃辣", is_update=True),
            PreferenceRecord(category="常驻城市", content="上海", is_update=True),
        ),
    )
    result = preference_agent.run({"user_input": "我现在常住上海，我改吃辣了", "user_id": "u1", "_defer_writes": True})
    writes = {w["category"]: w for w in result["memory_writes"]}
    assert writes["餐饮"]["is_update"] is True
    assert writes["餐饮"]["content"] == "吃辣"
    assert writes["常驻城市"]["content"] == "上海"
    assert "已更新偏好：常驻城市｜上海" in result["answer"]


def test_multi_record_produces_multiple_lines(monkeypatch):
    """路径 3：一条消息多个偏好 → 逐条写入、逐条话术。"""
    monkeypatch.setattr(
        preference_agent,
        "_invoke_pref_model",
        lambda text: _prefs(
            PreferenceRecord(category="住宿", content="喜欢住汉庭", is_update=False),
            PreferenceRecord(category="常驻城市", content="上海", is_update=True),
        ),
    )
    result = preference_agent.run({"user_input": "我喜欢住汉庭，常住上海", "user_id": "u1", "_defer_writes": True})
    assert len(result["memory_writes"]) == 2
    assert "已新增偏好：住宿｜喜欢住汉庭" in result["answer"]
    assert "已更新偏好：常驻城市｜上海" in result["answer"]


def test_empty_records_asks_question_not_writes(monkeypatch):
    """路径 4：疑问句/无偏好陈述 → 询问话术、零写入（防垃圾数据污染长期记忆）。"""
    monkeypatch.setattr(
        preference_agent,
        "_invoke_pref_model",
        lambda text: _prefs(),
    )
    result = preference_agent.run({"user_input": "我的住宿偏好是什么？", "user_id": "u1", "_defer_writes": True})
    assert "这是询问而非偏好陈述" in result["answer"]
    assert "memory_writes" not in result


def test_direct_write_calls_memory_store(monkeypatch):
    """路径 5：非 defer（直接调用路径）→ 真实调 memory.add_or_update_preference。"""
    stored = []

    def fake_add(category, content, is_update, session_id=None):
        stored.append((category, content, is_update, session_id))
        return {"category": category, "content": content, "ts": "2026-08-18 10:00"}

    monkeypatch.setattr(
        preference_agent,
        "_invoke_pref_model",
        lambda text: _prefs(PreferenceRecord(category="餐饮", content="不吃辣", is_update=False)),
    )
    monkeypatch.setattr(preference_agent, "add_or_update_preference", fake_add)
    result = preference_agent.run({"user_input": "我不吃辣", "user_id": "u1"})
    assert stored == [("餐饮", "不吃辣", False, "u1")]
    assert "已新增偏好：餐饮｜不吃辣" in result["answer"]


def test_cancelled_raises_without_partial_writes(monkeypatch):
    """路径 6：请求取消 → 抛 RuntimeError（主管不得提交不完整结果）。"""
    calls = {"n": 0}

    def flaky_model(text):
        calls["n"] += 1
        if calls["n"] == 1:
            return _prefs(PreferenceRecord(category="住宿", content="喜欢安静", is_update=False))
        raise RuntimeError("已取消")

    monkeypatch.setattr(preference_agent, "_invoke_pref_model", flaky_model)
    with pytest.raises(RuntimeError, match="已取消"):
        preference_agent.run(
            {
                "user_input": "住宿喜欢安静",
                "user_id": "u1",
                "_defer_writes": True,
                "_cancelled": lambda: calls["n"] >= 1,
            }
        )
