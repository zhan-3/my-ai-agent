"""Postgres 记忆后端（产品持久化 + 会话隔离）：psycopg 直连，三张表按 session 过滤

- 惰性短连接（每操作 connect；演示级规模足够，避免连接池复杂度——需要并发再上池）
- 幂等建表 CREATE TABLE IF NOT EXISTS；ts 保持字符串格式（数据形状与 InMemory 一致）
- 会话隔离：所有读写 WHERE session_id = %s
"""

import time

import psycopg
from psycopg.types.json import Jsonb

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE TABLE IF NOT EXISTS preferences (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_preferences_session ON preferences(session_id);
CREATE TABLE IF NOT EXISTS itineraries (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    facts JSONB NOT NULL,
    summary TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_itineraries_session ON itineraries(session_id);
"""


class PostgresBackend:
    """Postgres 后端：messages/preferences/itineraries 三表 + session_id 列"""

    def __init__(self, url: str) -> None:
        self._url = url
        self._ensure_schema()

    # ---------- 连接与建表 ----------
    def _conn(self):
        return psycopg.connect(self._url)

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(_SCHEMA)
            conn.commit()

    def clear_all(self) -> None:
        """清空三表（测试专用：保证每个用例干净起点）"""
        with self._conn() as conn:
            for t in ("messages", "preferences", "itineraries"):
                conn.execute(f"DELETE FROM {t}")
            conn.commit()

    # ---------- 短期记忆：消息 ----------
    def add_message(self, session_id: str, role: str, content: str) -> dict:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, ts) VALUES (%s, %s, %s, %s)",
                (session_id, role, content, ts),
            )
        return {"role": role, "content": content, "ts": ts}

    def get_recent_messages(self, session_id: str, n: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content, ts FROM messages WHERE session_id = %s ORDER BY id DESC LIMIT %s",
                (session_id, n),
            ).fetchall()
        return [{"role": r[0], "content": r[1], "ts": r[2]} for r in reversed(rows)]

    # ---------- 长期记忆：偏好（追加 / 覆盖） ----------
    def add_or_update_preference(self, session_id: str, category: str, content: str, is_update: bool = False) -> dict:
        ts = time.strftime("%Y-%m-%d %H:%M")
        with self._conn() as conn:
            if is_update:
                conn.execute(
                    "DELETE FROM preferences WHERE session_id = %s AND category = %s",
                    (session_id, category),
                )
            conn.execute(
                "INSERT INTO preferences (session_id, category, content, ts) VALUES (%s, %s, %s, %s)",
                (session_id, category, content, ts),
            )
        return {"category": category, "content": content, "ts": ts}

    def get_preferences(self, session_id: str, category: str | None = None) -> list[dict]:
        sql = "SELECT category, content, ts FROM preferences WHERE session_id = %s"
        args = [session_id]
        if category:
            sql += " AND category = %s"
            args.append(category)
        sql += " ORDER BY id"
        with self._conn() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [{"category": r[0], "content": r[1], "ts": r[2]} for r in rows]

    # ---------- 长期记忆：历史行程 ----------
    def add_itinerary(self, session_id: str, facts: dict, summary: str) -> dict:
        ts = time.strftime("%Y-%m-%d %H:%M")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO itineraries (session_id, facts, summary, ts) VALUES (%s, %s, %s, %s)",
                (session_id, Jsonb(facts), summary, ts),
            )
        return {**facts, "summary": summary, "ts": ts}

    def get_itineraries(self, session_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT facts, summary, ts FROM itineraries WHERE session_id = %s ORDER BY id",
                (session_id,),
            ).fetchall()
        return [{**r[0], "summary": r[1], "ts": r[2]} for r in rows]

    # ---------- 探活（stability 健康检查用） ----------
    def health_check(self) -> None:
        """SELECT 1 + 写读回探活（health 专用 session，用后即清）"""
        with self._conn() as conn:
            conn.execute("SELECT 1")
        self.add_message("__health__", "user", "ping")
        got = self.get_recent_messages("__health__", 1)
        assert got and got[-1]["content"] == "ping"
        with self._conn() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = %s", ("__health__",))
