"""Postgres 记忆后端：线程消息、活跃任务与用户长期记忆持久化

- 惰性短连接（每操作 connect；演示级规模足够，避免连接池复杂度——需要并发再上池）
- 幂等建表 CREATE TABLE IF NOT EXISTS；ts 保持字符串格式（数据形状与协议约定一致）
- 会话隔离：所有读写 WHERE session_id = %s
"""

import time
from contextlib import contextmanager
from threading import local

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
CREATE TABLE IF NOT EXISTS agent_transcripts (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    transcript JSONB NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_transcripts_session ON agent_transcripts(session_id);
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
CREATE TABLE IF NOT EXISTS active_tasks (
    thread_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    task JSONB NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_active_tasks_user ON active_tasks(user_id);
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class PostgresBackend:
    """Postgres 后端：线程消息/任务 + 用户偏好/行程。"""

    def __init__(self, url: str) -> None:
        self._url = url
        self._local = local()
        self._ensure_schema()

    # ---------- 连接与建表 ----------
    def _conn(self):
        return psycopg.connect(self._url)

    @contextmanager
    def _connection(self):
        active = getattr(self._local, "connection", None)
        if active is not None:
            yield active
            return
        with self._conn() as conn:
            yield conn

    @contextmanager
    def transaction(self):
        """同一线程内把多个记忆操作收口到一个 Postgres 事务。"""
        if getattr(self._local, "connection", None) is not None:
            yield
            return
        conn = self._conn()
        self._local.connection = conn
        try:
            yield
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            del self._local.connection
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connection() as conn:
            conn.execute(_SCHEMA)
            conn.commit()

    def clear_all(self) -> None:
        """清空业务表（测试专用：保证每个用例干净起点）"""
        with self._connection() as conn:
            for t in ("messages", "agent_transcripts", "preferences", "itineraries", "active_tasks"):
                conn.execute(f"DELETE FROM {t}")
            conn.commit()

    # ---------- 短期记忆：消息 ----------
    def add_message(self, session_id: str, role: str, content: str) -> dict:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, ts) VALUES (%s, %s, %s, %s)",
                (session_id, role, content, ts),
            )
        return {"role": role, "content": content, "ts": ts}

    def get_recent_messages(self, session_id: str, n: int) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT role, content, ts FROM messages WHERE session_id = %s ORDER BY id DESC LIMIT %s",
                (session_id, n),
            ).fetchall()
        return [{"role": r[0], "content": r[1], "ts": r[2]} for r in reversed(rows)]

    def add_agent_transcript(self, session_id: str, transcript: list[dict]) -> dict:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO agent_transcripts (session_id, transcript, ts) VALUES (%s, %s, %s)",
                (session_id, Jsonb(transcript), ts),
            )
        return {"transcript": transcript, "ts": ts}

    def get_recent_agent_transcripts(self, session_id: str, n: int) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT transcript, ts FROM agent_transcripts WHERE session_id = %s ORDER BY id DESC LIMIT %s",
                (session_id, n),
            ).fetchall()
        return [{"transcript": row[0], "ts": row[1]} for row in reversed(rows)]

    # ---------- 对话状态：每个 thread 最多一个活跃任务 ----------
    def get_active_task(self, thread_id: str, user_id: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT task FROM active_tasks WHERE thread_id = %s AND user_id = %s",
                (thread_id, user_id),
            ).fetchone()
        return row[0] if row else None

    def set_active_task(self, thread_id: str, user_id: str, task: dict) -> dict:
        updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO active_tasks (thread_id, user_id, task, updated_at) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (thread_id) DO UPDATE SET user_id = EXCLUDED.user_id, "
                "task = EXCLUDED.task, updated_at = EXCLUDED.updated_at",
                (thread_id, user_id, Jsonb(task), updated_at),
            )
        return task

    def clear_active_task(self, thread_id: str, user_id: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM active_tasks WHERE thread_id = %s AND user_id = %s",
                (thread_id, user_id),
            )

    # ---------- 长期记忆：偏好（追加 / 覆盖） ----------
    def add_or_update_preference(self, session_id: str, category: str, content: str, is_update: bool = False) -> dict:
        ts = time.strftime("%Y-%m-%d %H:%M")
        with self._connection() as conn:
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
        with self._connection() as conn:
            rows = conn.execute(sql, tuple(args)).fetchall()
        return [{"category": r[0], "content": r[1], "ts": r[2]} for r in rows]

    # ---------- 长期记忆：历史行程 ----------
    def add_itinerary(self, session_id: str, facts: dict, summary: str) -> dict:
        """写入行程；相同出发日/路线/天数的候选更新原记录，避免重试产生重复档案。

        缺少完整身份字段的旧数据仍追加，保持历史数据和兼容调用语义不变。
        """
        ts = time.strftime("%Y-%m-%d %H:%M")
        identity = tuple(facts.get(key) for key in ("start_date", "from_city", "to_city", "duration_days"))
        with self._connection() as conn:
            row = None
            if all(value not in (None, "", "待定", "未知", 0) for value in identity):
                row = conn.execute(
                    "SELECT id FROM itineraries WHERE session_id = %s "
                    "AND facts->>'start_date' = %s AND facts->>'from_city' = %s "
                    "AND facts->>'to_city' = %s AND facts->>'duration_days' = %s "
                    "ORDER BY id DESC LIMIT 1",
                    (session_id, *(str(value) for value in identity)),
                ).fetchone()
            if row:
                conn.execute(
                    "UPDATE itineraries SET facts = %s, summary = %s, ts = %s WHERE id = %s",
                    (Jsonb(facts), summary, ts, row[0]),
                )
            else:
                conn.execute(
                    "INSERT INTO itineraries (session_id, facts, summary, ts) VALUES (%s, %s, %s, %s)",
                    (session_id, Jsonb(facts), summary, ts),
                )
        return {**facts, "summary": summary, "ts": ts}

    def get_itineraries(self, session_id: str) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT facts, summary, ts FROM itineraries WHERE session_id = %s ORDER BY id",
                (session_id,),
            ).fetchall()
        return [{**r[0], "summary": r[1], "ts": r[2]} for r in rows]

    # ---------- 只读探活（stability 健康检查用） ----------
    def health_check(self) -> None:
        """用 SELECT 1 验证连接，不写入业务表。"""
        with self._connection() as conn:
            conn.execute("SELECT 1")


class PostgresUserStore:
    """认证用户存储：users 表（username 唯一，只存 bcrypt 哈希）

    独立于记忆三域（认证域专属）；短连接 + 幂等建表，与 PostgresBackend 同模式。
    """

    def __init__(self, url: str) -> None:
        self._url = url
        with psycopg.connect(url) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                " id BIGSERIAL PRIMARY KEY,"
                " username TEXT NOT NULL UNIQUE,"
                " password_hash TEXT NOT NULL,"
                " created_at TEXT NOT NULL)"
            )
            conn.commit()

    def register(self, username: str, password_hash: str) -> dict | None:
        try:
            with psycopg.connect(self._url) as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (%s, %s, %s)",
                    (username, password_hash, time.strftime("%Y-%m-%d %H:%M")),
                )
                conn.commit()
        except psycopg.errors.UniqueViolation:
            return None
        return {"username": username, "password_hash": password_hash}

    def get_user(self, username: str) -> dict | None:
        with psycopg.connect(self._url) as conn:
            row = conn.execute("SELECT username, password_hash FROM users WHERE username = %s", (username,)).fetchone()
        if row is None:
            return None
        return {"username": row[0], "password_hash": row[1]}

    def clear_all(self) -> None:
        """清空用户表（测试专用）"""
        with psycopg.connect(self._url) as conn:
            conn.execute("DELETE FROM users")
            conn.commit()
