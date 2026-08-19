"""记忆后端协议 + 会话隔离（S1/S2）：PostgresBackend 直测 + memory 函数委托 + session 隔离矩阵

- S1：MemoryBackend 协议（8 方法）+ PostgresBackend（唯一后端）
- S2：核心验收——同一后端下 session A 写消息/偏好/行程，session B 三域全空；
  组合函数（常驻城市/常用目的地）也按 session 隔离
- 隔离由 conftest autouse fixture 保证（每测试前 clear_all 全部业务表）
"""

import os
import threading
import time

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


def test_agent_transcript_module_roundtrip():
    _fresh()
    transcript = [{"role": "assistant", "content": "", "tool_calls": [{"name": "agent_0"}]}]
    memory.add_agent_transcript(transcript, session_id="A")
    assert memory.get_recent_agent_transcripts(1, session_id="A")[0]["transcript"] == transcript
    assert memory.get_recent_agent_transcripts(1, session_id="B") == []


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


def test_get_latest_trip_excludes_completed():
    """最近可改行程：只返回 upcoming/drafting；已结束（completed）被排除。"""
    _fresh()
    # 过去日期 → completed（读时派生），不可再改
    memory.save_trip(
        {"start_date": "2020-01-01", "to_city": "北京", "from_city": "临沂", "duration_days": 2},
        {"summary": "旧行程"},
        session_id="A",
    )
    assert memory.get_latest_trip(session_id="A") is None
    # 未来日期 → upcoming，命中
    memory.save_trip(
        {"start_date": "2026-09-01", "to_city": "武汉", "from_city": "临沂", "duration_days": 2},
        {"summary": "新行程"},
        session_id="A",
    )
    latest = memory.get_latest_trip(session_id="A")
    assert latest is not None and latest["to_city"] == "武汉" and latest["status"] == "upcoming"
    assert latest["id"] is not None


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


def test_thread_task_is_separate_from_user_long_term_memory():
    _fresh()
    task = {"intent": "行程规划", "missing": ["出差天数"]}
    memory.set_active_task(task, thread_id="alice:one", user_id="alice")
    memory.add_or_update_preference("餐饮", "不吃辣", session_id="alice")

    got = memory.get_active_task(thread_id="alice:one", user_id="alice")
    assert got is not None
    assert got["intent"] == "行程规划" and got["missing"] == ["出差天数"]
    assert memory.get_active_task(thread_id="alice:two", user_id="alice") is None
    assert memory.get_preferences(session_id="alice")[-1]["content"] == "不吃辣"


# ---------- S3：后端就绪约束（单后端：必须配 POSTGRES_URL） ----------


def test_get_backend_requires_postgres_url(monkeypatch):
    """未配 POSTGRES_URL 时明确报错。"""
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.delenv("POSTGRES_TEST_URL", raising=False)
    memory._backend = None
    try:
        with pytest.raises(RuntimeError, match="POSTGRES_URL"):
            memory._get_backend()
    finally:
        memory._backend = None


def test_get_backend_initializes_once_under_concurrency(monkeypatch):
    """并发首屏请求只能构造一次后端，避免两个线程同时执行 schema DDL。"""
    import xiao_wen.memory_pg as memory_pg

    constructed = []

    class FakeBackend:
        def __init__(self, url):
            time.sleep(0.02)
            constructed.append(url)

    monkeypatch.setattr(memory_pg, "PostgresBackend", FakeBackend)
    monkeypatch.setenv("POSTGRES_URL", "postgresql://test")
    monkeypatch.delenv("POSTGRES_TEST_URL", raising=False)
    memory._backend = None
    barrier = threading.Barrier(8)
    results = []

    def get_backend():
        barrier.wait()
        results.append(memory._get_backend())

    threads = [threading.Thread(target=get_backend) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert constructed == ["postgresql://test"]
    assert len({id(result) for result in results}) == 1
