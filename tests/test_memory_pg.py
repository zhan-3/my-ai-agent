"""Postgres 后端（S3）：真库测试，标 postgres 标记（本地有容器/原生 PG 且 POSTGRES_TEST_URL 才跑）

覆盖：幂等建表、消息/偏好/行程三域读写 + session 隔离、只读 health_check 探活
"""

import os
import pytest

pg_url = os.environ["POSTGRES_TEST_URL"]  # conftest 已强制存在，绝不回退开发库

from xiao_wen.memory_pg import PostgresBackend  # noqa: E402


class TestPostgresBackend:
    """PostgresBackend 直测：8 方法 + 幂等建表 + session 隔离"""

    @pytest.fixture()
    def b(self):
        backend = PostgresBackend(pg_url)
        backend.clear_all()  # 干净起点（测试专用清理）
        yield backend
        backend.clear_all()

    def test_schema_idempotent(self, b):
        b._ensure_schema()  # 二次调用不炸（CREATE TABLE IF NOT EXISTS）
        b._ensure_schema()

    def test_messages_roundtrip_and_isolated(self, b):
        b.add_message("A", "user", "你好")
        b.add_message("A", "assistant", "回")
        b.add_message("B", "user", "B的消息")
        assert [m["content"] for m in b.get_recent_messages("A", 6)] == ["你好", "回"]
        assert [m["content"] for m in b.get_recent_messages("B", 6)] == ["B的消息"]
        assert b.get_recent_messages("C", 6) == []

    def test_agent_transcripts_roundtrip_and_isolated(self, b):
        transcript = [{"role": "assistant", "tool_calls": [{"name": "agent_0"}]}, {"role": "tool", "content": "结果"}]
        b.add_agent_transcript("A", transcript)
        assert b.get_recent_agent_transcripts("A", 1)[0]["transcript"] == transcript
        assert b.get_recent_agent_transcripts("B", 1) == []

    def test_preferences_override_and_isolated(self, b):
        b.add_or_update_preference("A", "常驻城市", "上海")
        b.add_or_update_preference("A", "常驻城市", "北京", is_update=True)
        b.add_or_update_preference("B", "常驻城市", "广州")
        assert [p["content"] for p in b.get_preferences("A", "常驻城市")] == ["北京"]  # 覆盖不追加
        assert [p["content"] for p in b.get_preferences("A")] == ["北京"]
        assert [p["content"] for p in b.get_preferences("B")] == ["广州"]

    def test_preference_duplicate_declaration_is_idempotent(self, b):
        """同一用户重复声明完全相同偏好（is_update=False）不重复追加（曾致「我喜欢住全季」说两次 → 两条）。"""
        b.add_or_update_preference("A", "住宿", "喜欢住全季")
        b.add_or_update_preference("A", "住宿", "喜欢住全季")
        b.add_or_update_preference("A", "住宿", "喜欢住全季")
        assert [p["content"] for p in b.get_preferences("A", "住宿")] == ["喜欢住全季"]
        # 内容不同仍追加（不是去重过头）；is_update 覆盖语义不受影响
        b.add_or_update_preference("A", "住宿", "喜欢住汉庭")
        assert [p["content"] for p in b.get_preferences("A", "住宿")] == ["喜欢住全季", "喜欢住汉庭"]

    def test_active_task_roundtrip_and_user_guard(self, b):
        task = {"intent": "行程规划", "missing": ["出发城市"]}
        b.set_active_task("alice:thread-a", "alice", task)
        got = b.get_active_task("alice:thread-a", "alice")
        assert got["intent"] == "行程规划"
        assert got["missing"] == ["出发城市"]
        assert got["trip_id"] is not None  # 新架构：活跃任务绑定 trips.drafting 行的 id
        assert b.get_active_task("alice:thread-a", "bob") is None
        b.clear_active_task("alice:thread-a", "bob")
        assert b.get_active_task("alice:thread-a", "alice")["trip_id"] is not None
        b.clear_active_task("alice:thread-a", "alice")
        assert b.get_active_task("alice:thread-a", "alice") is None

    def test_itineraries_roundtrip_and_isolated(self, b):
        b.add_itinerary("A", {"to_city": "北京"}, "北京出差")
        b.add_itinerary("A", {"to_city": "杭州"}, "杭州出差")
        b.add_itinerary("B", {"to_city": "深圳"}, "深圳出差")
        assert [i["to_city"] for i in b.get_itineraries("A")] == ["北京", "杭州"]
        assert [i["summary"] for i in b.get_itineraries("B")] == ["深圳出差"]
        assert b.get_itineraries("C") == []

    def test_health_check_probe(self, b):
        b.add_message("keep", "user", "untouched")
        b.health_check()
        assert b.get_recent_messages("keep", 1)[0]["content"] == "untouched"


class TestPostgresPersistence:
    """S6 持久化验收：写记忆 → 丢弃后端（模拟进程重启）→ 新连接数据仍在"""

    def test_survives_backend_recreation(self):
        b1 = PostgresBackend(pg_url)
        b1.clear_all()
        b1.add_message("A", "user", "重启前的消息")
        b1.add_or_update_preference("A", "常驻城市", "上海")
        b1.add_itinerary("A", {"to_city": "北京"}, "重启前的行程")
        del b1  # 丢弃连接对象（模拟进程重启，无任何内存态）

        b2 = PostgresBackend(pg_url)  # 新连接：从磁盘读
        assert b2.get_recent_messages("A", 6)[0]["content"] == "重启前的消息"
        assert [p["content"] for p in b2.get_preferences("A", "常驻城市")] == ["上海"]
        assert [i["to_city"] for i in b2.get_itineraries("A")] == ["北京"]
        # 隔离仍成立：B 会话无数据
        assert b2.get_recent_messages("B", 6) == []
        b2.clear_all()
