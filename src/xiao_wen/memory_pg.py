"""Postgres 记忆后端：线程消息、活跃任务与用户长期记忆持久化

- 惰性短连接（每操作 connect；单体单 worker 规模足够，避免连接池复杂度——需要并发再上池）
- 幂等建表 CREATE TABLE IF NOT EXISTS；ts 保持字符串格式（数据形状与协议约定一致）
- 会话隔离：所有读写 WHERE session_id = %s
"""

import logging
import time
from contextlib import contextmanager
from datetime import date, timedelta
from threading import local

import psycopg
from psycopg.types.json import Jsonb

logger = logging.getLogger("xiao_wen.memory_pg")

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
CREATE TABLE IF NOT EXISTS trips (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    thread_id TEXT,
    status TEXT NOT NULL DEFAULT 'upcoming',
    facts JSONB NOT NULL DEFAULT '{}',
    plan JSONB,
    missing JSONB NOT NULL DEFAULT '[]',
    resume_context TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trips_user ON trips(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_trips_thread ON trips(thread_id, updated_at);
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# 旧表（itineraries / active_tasks）被 trips 取代（ADR-0011）：启动时幂等移除，数据不保留。
_LEGACY_DROP = """
DROP TABLE IF EXISTS itineraries;
DROP TABLE IF EXISTS active_tasks;
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
        except Exception as exc:
            logger.error("事务回滚：%s", exc, exc_info=True)
            conn.rollback()
            raise
        finally:
            del self._local.connection
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connection() as conn:
            conn.execute(_LEGACY_DROP)
            conn.execute(_SCHEMA)
            conn.commit()

    def clear_all(self) -> None:
        """清空业务表（测试专用：保证每个用例干净起点）"""
        with self._connection() as conn:
            for t in ("messages", "agent_transcripts", "preferences", "trips"):
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

    # ---------- 对话状态：线程内 drafting 行程（兼容旧「活跃任务」接口，ADR-0011） ----------
    def get_active_task(self, thread_id: str, user_id: str) -> dict | None:
        """线程内最近一条 drafting 行程，包装成旧活跃任务形状（intent/resume_context/missing + trip_id）。"""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, facts, missing, resume_context FROM trips "
                "WHERE thread_id = %s AND user_id = %s AND status = 'drafting' "
                "ORDER BY updated_at DESC, id DESC LIMIT 1",
                (thread_id, user_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "intent": "行程规划",
            "resume_context": row[3] or "",
            "missing": list(row[2] or []),
            "trip_id": row[0],
            "facts": dict(row[1] or {}),
        }

    def set_active_task(self, thread_id: str, user_id: str, task: dict) -> dict:
        """把旧活跃任务形状写回 trips 表：有 trip_id 更新原 drafting，否则按线程新建。"""
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        missing = list(task.get("missing") or [])
        resume_context = str(task.get("resume_context") or "")
        trip_id = task.get("trip_id")
        facts = dict(task.get("facts") or {})
        with self._connection() as conn:
            if trip_id is not None:
                conn.execute(
                    "UPDATE trips SET missing = %s, resume_context = %s, facts = %s, updated_at = %s "
                    "WHERE id = %s AND user_id = %s",
                    (Jsonb(missing), resume_context, Jsonb(facts), ts, trip_id, user_id),
                )
            else:
                conn.execute(
                    "INSERT INTO trips "
                    "(user_id, thread_id, status, facts, missing, resume_context, created_at, updated_at) "
                    "VALUES (%s, %s, 'drafting', %s, %s, %s, %s, %s)",
                    (user_id, thread_id, Jsonb(facts), Jsonb(missing), resume_context, ts, ts),
                )
                row = conn.execute(
                    "SELECT id FROM trips WHERE thread_id = %s AND user_id = %s AND status = 'drafting' "
                    "ORDER BY id DESC LIMIT 1",
                    (thread_id, user_id),
                ).fetchone()
                trip_id = row[0] if row else None
        return {**task, "intent": "行程规划", "trip_id": trip_id}

    def clear_active_task(self, thread_id: str, user_id: str) -> None:
        """行程完成：删除线程内 drafting 草稿（已生成待出发行程，草稿废弃）。"""
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM trips WHERE thread_id = %s AND user_id = %s AND status = 'drafting'",
                (thread_id, user_id),
            )

    def cancel_active_task(self, thread_id: str, user_id: str) -> None:
        """用户取消：线程内 drafting 草稿转 cancelled（保留记录不删除）。"""
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            conn.execute(
                "UPDATE trips SET status = 'cancelled', updated_at = %s "
                "WHERE thread_id = %s AND user_id = %s AND status = 'drafting'",
                (ts, thread_id, user_id),
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
            else:
                # 幂等去重：同一用户同类别已存在相同内容时不重复追加（「我喜欢住全季」说两次不应两条）。
                # 依赖 LLM 的 is_update 不稳定（同一输入偶发 True/False），去重必须代码层确定性保证。
                exists = conn.execute(
                    "SELECT 1 FROM preferences WHERE session_id = %s AND category = %s AND content = %s LIMIT 1",
                    (session_id, category, content),
                ).fetchone()
                if exists:
                    return {"category": category, "content": content, "ts": ts}
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

    # ---------- 长期记忆：行程（trips 表，ADR-0011 生命周期） ----------
    def _derived_status(self, status: str, facts: dict) -> str:
        """upcoming 且行程已结束（today > 最后一天）→ 展示为 completed（读时派生，不写库）。"""
        if status != "upcoming":
            return status
        raw = str((facts or {}).get("start_date", ""))[:10]
        try:
            start = date.fromisoformat(raw)
        except ValueError:
            return status
        dur = facts.get("duration_days")
        end = start + timedelta(days=(int(dur) - 1 if isinstance(dur, int) and dur > 0 else 0))
        return "completed" if end < date.today() else status

    def _trip_dict(self, row: tuple) -> dict:
        id_, thread_id, status, facts, plan, missing, resume_context, updated_at = row
        facts = dict(facts or {})
        plan = dict(plan) if plan else None
        return {
            "id": id_,
            "thread_id": thread_id or "",
            "status": self._derived_status(status, facts),
            **facts,
            "plan": plan,
            "summary": (plan or {}).get("summary", ""),
            "missing": list(missing or []),
            "resume_context": resume_context or "",
            "ts": updated_at,
        }

    def save_trip(
        self,
        user_id: str,
        facts: dict,
        plan: dict | None,
        *,
        thread_id: str | None = None,
        trip_id: int | None = None,
        status: str = "upcoming",
        missing: list | None = None,
        resume_context: str = "",
    ) -> dict:
        """写入/更新一条行程。trip_id 给定时更新同一条；否则按身份字段去重
        （出发日/路线/天数命中 → 更新原记录，避免重试产生重复档案）。
        """
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        missing = list(missing or [])
        plan_json = Jsonb(plan) if plan is not None else None
        with self._connection() as conn:
            if trip_id is not None:
                conn.execute(
                    "UPDATE trips SET facts = %s, plan = %s, status = %s, missing = %s, "
                    "resume_context = %s, thread_id = COALESCE(%s, thread_id), updated_at = %s "
                    "WHERE id = %s AND user_id = %s",
                    (Jsonb(facts), plan_json, status, Jsonb(missing), resume_context, thread_id, ts, trip_id, user_id),
                )
                row = conn.execute("SELECT id FROM trips WHERE id = %s", (trip_id,)).fetchone()
                stored_id = row[0] if row else None
            else:
                identity = tuple(facts.get(key) for key in ("start_date", "from_city", "to_city", "duration_days"))
                existing = None
                if all(value not in (None, "", "待定", "未知", 0) for value in identity):
                    existing = conn.execute(
                        "SELECT id FROM trips WHERE user_id = %s AND status != 'cancelled' "
                        "AND facts->>'start_date' = %s AND facts->>'from_city' = %s "
                        "AND facts->>'to_city' = %s AND facts->>'duration_days' = %s "
                        "ORDER BY id DESC LIMIT 1",
                        (user_id, *(str(value) for value in identity)),
                    ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE trips SET facts = %s, plan = %s, status = %s, missing = %s, "
                        "resume_context = %s, thread_id = COALESCE(%s, thread_id), updated_at = %s WHERE id = %s",
                        (Jsonb(facts), plan_json, status, Jsonb(missing), resume_context, thread_id, ts, existing[0]),
                    )
                    stored_id = existing[0]
                else:
                    conn.execute(
                        "INSERT INTO trips "
                        "(user_id, thread_id, status, facts, plan, missing, resume_context, created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (user_id, thread_id, status, Jsonb(facts), plan_json, Jsonb(missing), resume_context, ts, ts),
                    )
                    row = conn.execute(
                        "SELECT id FROM trips WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,)
                    ).fetchone()
                    stored_id = row[0] if row else None
        return {**facts, "summary": (plan or {}).get("summary", ""), "ts": ts, "id": stored_id, "status": status}

    def get_trips(self, user_id: str) -> list[dict]:
        """当前用户全部非取消行程（含 drafting），status 已按日期派生（completed 读时判定）。"""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id, thread_id, status, facts, plan, missing, resume_context, updated_at "
                "FROM trips WHERE user_id = %s AND status != 'cancelled' ORDER BY id",
                (user_id,),
            ).fetchall()
        return [self._trip_dict(row) for row in rows]

    def get_trip(self, user_id: str, trip_id: int) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, thread_id, status, facts, plan, missing, resume_context, updated_at "
                "FROM trips WHERE user_id = %s AND id = %s",
                (user_id, trip_id),
            ).fetchone()
        return self._trip_dict(row) if row else None

    def update_trip(
        self,
        user_id: str,
        trip_id: int,
        *,
        facts: dict | None = None,
        plan: dict | None = None,
        status: str | None = None,
    ) -> dict | None:
        """改期/改细节：更新同一条行程（id 不变）。未找到返回 None。"""
        current = self.get_trip(user_id, trip_id)
        if current is None:
            return None
        merged_facts = {
            **{
                k: v
                for k, v in current.items()
                if k not in ("id", "status", "plan", "summary", "missing", "resume_context", "ts")
            },
            **(facts or {}),
        }
        return self.save_trip(
            user_id,
            merged_facts,
            plan if plan is not None else current.get("plan"),
            trip_id=trip_id,
            status=status or "upcoming",
        )

    def cancel_trip(self, user_id: str, trip_id: int) -> bool:
        """取消已确定行程（upcoming）→ cancelled。drafting 用 cancel_active_task。"""
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            cur = conn.execute(
                "UPDATE trips SET status = 'cancelled', updated_at = %s WHERE id = %s AND user_id = %s",
                (ts, trip_id, user_id),
            )
        return cur.rowcount > 0

    def duplicate_trip(self, user_id: str, trip_id: int) -> dict | None:
        """参考历史再来一次：复制 facts 开新行程（新 id，drafting 态待补全/重排）。"""
        current = self.get_trip(user_id, trip_id)
        if current is None:
            return None
        facts = {
            k: v
            for k, v in current.items()
            if k not in ("id", "status", "plan", "summary", "missing", "resume_context", "ts")
        }
        return self.save_trip(user_id, facts, None, status="drafting", missing=[])

    def add_itinerary(self, session_id: str, facts: dict, summary: str) -> dict:
        """兼容旧调用：写入已确定行程（plan 仅 summary）。相同出发日/路线/天数的候选更新原记录。"""
        return self.save_trip(session_id, facts, {"summary": summary}, status="upcoming")

    def get_itineraries(self, session_id: str) -> list[dict]:
        """兼容旧调用：已确定行程（非 drafting/取消），facts 展开 + summary。"""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id, thread_id, status, facts, plan, missing, resume_context, updated_at "
                "FROM trips WHERE user_id = %s AND status IN ('upcoming', 'completed') ORDER BY id",
                (session_id,),
            ).fetchall()
        return [self._trip_dict(row) for row in rows]

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
