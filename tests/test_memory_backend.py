"""记忆后端协议 + 会话隔离（S1/S2）：InMemoryBackend 直测 + memory 函数委托 + session 隔离矩阵

- S1：MemoryBackend 协议（8 方法）+ InMemoryBackend + set_backend 注入
- S2：核心验收——同一后端下 session A 写消息/偏好/行程，session B 三域全空；
  组合函数（常驻城市/常用目的地）也按 session 隔离
"""

import xiao_wen.memory as memory


def _fresh() -> memory.InMemoryBackend:
    """注入全新 InMemoryBackend 并返回（每次测试独立隔离）"""
    b = memory.InMemoryBackend()
    memory.set_backend(b)
    return b


# ---------- S1：InMemoryBackend 协议直测 ----------


def test_inmemory_backend_messages_append_in_order():
    b = _fresh()
    b.add_message("A", "user", "你好")
    b.add_message("A", "assistant", "你好，有什么可以帮你？")
    recent = b.get_recent_messages("A", 6)
    assert [m["role"] for m in recent] == ["user", "assistant"]
    assert recent[1]["content"].startswith("你好")


def test_inmemory_backend_preference_update_overrides_category():
    b = _fresh()
    b.add_or_update_preference("A", "常驻城市", "上海")
    b.add_or_update_preference("A", "常驻城市", "北京", is_update=True)
    assert [p["content"] for p in b.get_preferences("A", "常驻城市")] == ["北京"]  # 覆盖不追加
    assert [p["content"] for p in b.get_preferences("A")] == ["北京"]


def test_inmemory_backend_itinerary_roundtrip():
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


# ---------- S4：env 分派（PostgresBackend 用假类隔离，不碰真库） ----------


def test_backend_dispatch_without_env_uses_inmemory(monkeypatch):
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    memory._backend = None  # 重置惰性分派
    assert isinstance(memory._get_backend(), memory.InMemoryBackend)
    memory._backend = None


def test_backend_dispatch_with_env_uses_postgres(monkeypatch):
    import xiao_wen.memory_pg as pg

    calls: list[str] = []

    class FakePG:
        def __init__(self, url: str):
            calls.append(url)

    monkeypatch.setattr(pg, "PostgresBackend", FakePG)
    monkeypatch.setenv("POSTGRES_URL", "postgresql://xw:xw@localhost:5432/xiao_wen")
    memory._backend = None
    memory._get_backend()
    assert calls == ["postgresql://xw:xw@localhost:5432/xiao_wen"]
    memory._backend = None
