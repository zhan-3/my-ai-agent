"""记忆后端协议 + 会话隔离（S1/S2）：PostgresBackend 直测 + memory 函数委托 + session 隔离矩阵

- S1：MemoryBackend 协议（8 方法）+ PostgresBackend（唯一后端）
- S2：核心验收——同一后端下 session A 写消息/偏好/行程，session B 三域全空；
  组合函数（常驻城市/常用目的地）也按 session 隔离
- 隔离由 conftest autouse fixture 保证（每测试前 clear_all 三张表）
"""

import os

import pytest

import xiao_wen.memory as memory
from xiao_wen.memory_pg import PostgresBackend


def _fresh() -> PostgresBackend:
    """注入全新 PostgresBackend（同一测试库）并返回（每测试独立隔离由 conftest 清表保证）"""
    url = os.environ.get("POSTGRES_TEST_URL") or os.environ["POSTGRES_URL"]
    b = PostgresBackend(url)
    b.clear_all()
    memory.set_backend(b)
    return b


# ---------- S1：PostgresBackend 协议直测 ----------


def test_backend_messages_append_in_order():
    b = _fresh()
    b.add_message("A", "user", "你好")
    b.add_message("A", "assistant", "你好，有什么可以帮你？")
    recent = b.get_recent_messages("A", 6)
    assert [m["role"] for m in recent] == ["user", "assistant"]
    assert recent[1]["content"].startswith("你好")


def test_backend_preference_update_overrides_category():
    b = _fresh()
    b.add_or_update_preference("A", "常驻城市", "上海")
    b.add_or_update_preference("A", "常驻城市", "北京", is_update=True)
    assert [p["content"] for p in b.get_preferences("A", "常驻城市")] == ["北京"]  # 覆盖不追加
    assert [p["content"] for p in b.get_preferences("A")] == ["北京"]


def test_backend_itinerary_same_trip_is_upserted():
    b = _fresh()
    facts = {"start_date": "2026-08-18", "from_city": "临沂", "to_city": "广州", "duration_days": 5}
    b.add_itinerary("A", facts, "第一次生成")
    b.add_itinerary("A", facts, "重试后生成")
    its = b.get_itineraries("A")
    assert len(its) == 1
    assert its[0]["summary"] == "重试后生成"


def test_backend_itinerary_roundtrip():
    b = _fresh()
    rec = b.add_itinerary("A", {"to_city": "北京"}, "北京出差")
    assert rec["to_city"] == "北京" and rec["summary"] == "北京出差"
    its = b.get_itineraries("A")
    assert its[0]["to_city"] == "北京"  # facts 扁平化进 rec（与现有行为一致）


# ---------- S2：会话隔离（核心验收） ----------


def test_session_isolation_matrix():
    """A 写消息/偏好/行程 → B 三域全空；A 侧可见"""
    _fresh()
    memory.add_message("user", "A的消息", session_id="A")
    memory.add_or_update_preference("常驻城市", "上海", session_id="A")
    memory.add_itinerary({"to_city": "北京"}, "A的行程", session_id="A")

    assert memory.get_recent_messages(6, session_id="B") == []
    assert memory.get_preferences(session_id="B") == []
    assert memory.get_itineraries(session_id="B") == []
    assert memory.get_recent_messages(6, session_id="A")[-1]["content"] == "A的消息"


def test_home_city_and_common_destinations_isolated():
    _fresh()
    memory.add_or_update_preference("常驻城市", "上海", session_id="A")
    memory.add_itinerary({"to_city": "北京"}, "t1", session_id="A")
    memory.add_itinerary({"to_city": "北京"}, "t2", session_id="A")
    memory.add_itinerary({"to_city": "杭州"}, "t3", session_id="A")

    assert memory.get_home_city(session_id="A") == "上海"
    assert memory.get_common_destinations(n=3, session_id="A") == ["北京", "杭州"]
    assert memory.get_home_city(session_id="B") is None
    assert memory.get_common_destinations(session_id="B") == []


def test_default_session_compat():
    """不传 session_id = "default"（现有调用点零改动）；显式 default 与不传等同，其他 session 隔离"""
    _fresh()
    memory.add_message("user", "兼容消息")
    assert memory.get_recent_messages(6)[-1]["content"] == "兼容消息"
    assert memory.get_recent_messages(6, session_id="default")[-1]["content"] == "兼容消息"
    assert memory.get_recent_messages(6, session_id="其他") == []


# ---------- S3：后端就绪约束（单后端：必须配 POSTGRES_URL） ----------


def test_get_backend_requires_postgres_url(monkeypatch):
    """未配 POSTGRES_URL → 明确报错（不再静默内存兜底）"""
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    memory._backend = None
    try:
        with pytest.raises(RuntimeError, match="POSTGRES_URL"):
            memory._get_backend()
    finally:
        memory._backend = None
