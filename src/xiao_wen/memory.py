"""记忆模块：短期 + 长期两层记忆（唯一产品后端：Postgres）

- 会话隔离：所有记忆按 session_id 隔离（默认 "default"，向后兼容既有调用点）
- 后端协议 MemoryBackend（三个域：消息/偏好/行程的按 session 读写），
  唯一实现 PostgresBackend（memory_pg.py，psycopg，POSTGRES_URL 必配）
- 组合函数留在函数层：format_recent_messages / get_home_city / get_common_destinations
  （backend 只管基础读写，组合逻辑不重复）
- 测试注入：set_backend(PostgresBackend(test_url)) 指向专用测试库
  （conftest 负责清表；本模块不提供进程内存后端）
"""

from collections import Counter
from contextlib import contextmanager
from threading import Lock
from typing import Protocol

from xiao_wen.config import load_settings


class MemoryBackend(Protocol):
    """记忆存储后端协议：三个域（消息/偏好/行程）按 session 的基础读写"""

    def add_message(self, session_id: str, role: str, content: str) -> dict: ...

    def get_recent_messages(self, session_id: str, n: int) -> list[dict]: ...

    def add_agent_transcript(self, session_id: str, transcript: list[dict]) -> dict: ...

    def get_recent_agent_transcripts(self, session_id: str, n: int) -> list[dict]: ...

    def get_active_task(self, thread_id: str, user_id: str) -> dict | None: ...

    def set_active_task(self, thread_id: str, user_id: str, task: dict) -> dict: ...

    def clear_active_task(self, thread_id: str, user_id: str) -> None: ...

    def add_or_update_preference(
        self, session_id: str, category: str, content: str, is_update: bool = False
    ) -> dict: ...

    def get_preferences(self, session_id: str, category: str | None = None) -> list[dict]: ...

    def add_itinerary(self, session_id: str, facts: dict, summary: str) -> dict: ...

    def get_itineraries(self, session_id: str) -> list[dict]: ...

    def transaction(self): ...

    def health_check(self) -> None: ...  # PostgresBackend：探活（连接失败抛异常）


# ---- 模块级当前后端（测试注入 set_backend；生产懒构造 Postgres） ----
_backend: MemoryBackend | None = None
_backend_lock = Lock()


def set_backend(backend: MemoryBackend) -> None:
    """注入后端（测试注入 PostgresBackend(test_url) 隔离；生产由 _get_backend 懒构造）"""
    global _backend  # noqa: PLW0603 —— 后端注入是模块级状态的刻意设计
    with _backend_lock:
        _backend = backend


def _get_backend() -> MemoryBackend:
    """懒构造唯一产品后端 Postgres；缺少 POSTGRES_URL 时直接报错。"""
    global _backend  # noqa: PLW0603
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                url = load_settings().require_postgres_url()
                from xiao_wen.memory_pg import PostgresBackend  # 懒导入：pg 依赖可选

                _backend = PostgresBackend(url)
    return _backend


# ---------- 短期记忆：最近 N 轮对话（session 维度） ----------
def add_message(role: str, content: str, *, session_id: str = "default") -> dict:
    return _get_backend().add_message(session_id, role, content)


def get_recent_messages(n: int = 6, *, session_id: str = "default") -> list[dict]:
    """最近 n 条消息（按时间正序）"""
    return _get_backend().get_recent_messages(session_id, n)


def format_recent_messages(n: int = 6, *, session_id: str = "default") -> str:
    """格式化为给 LLM 看的文本（供主管注入，hot path 注入要克制）

    每条最多 400 字：行程答案等长文本必须对 LLM 可见，
    否则追问行程细节时主管/子 Agent 只能凭截断文本脑补参数。
    """
    msgs = get_recent_messages(n, session_id=session_id)
    if not msgs:
        return "无"
    lines = [f"{'用户' if m['role'] == 'user' else '助手'}: {m['content'][:400]}" for m in msgs]
    return "\n".join(lines)


def add_agent_transcript(transcript: list[dict], *, session_id: str = "default") -> dict:
    return _get_backend().add_agent_transcript(session_id, transcript)


def get_recent_agent_transcripts(n: int = 6, *, session_id: str = "default") -> list[dict]:
    return _get_backend().get_recent_agent_transcripts(session_id, n)


@contextmanager
def transaction():
    with _get_backend().transaction():
        yield


# ---------- 对话状态：线程级活跃任务 ----------
def get_active_task(*, thread_id: str, user_id: str) -> dict | None:
    return _get_backend().get_active_task(thread_id, user_id)


def set_active_task(task: dict, *, thread_id: str, user_id: str) -> dict:
    return _get_backend().set_active_task(thread_id, user_id, task)


def clear_active_task(*, thread_id: str, user_id: str) -> None:
    _get_backend().clear_active_task(thread_id, user_id)


# ---------- 长期记忆：偏好（追加 / 覆盖） ----------
def add_or_update_preference(
    category: str, content: str, is_update: bool = False, *, session_id: str = "default"
) -> dict:
    """偏好写入。is_update=True 时替换同类别旧条目（如「我现在常住上海」更新常驻城市）"""
    return _get_backend().add_or_update_preference(session_id, category, content, is_update)


def get_preferences(category: str | None = None, *, session_id: str = "default") -> list[dict]:
    return _get_backend().get_preferences(session_id, category)


def get_home_city(*, session_id: str = "default") -> str | None:
    """常驻城市（长期信息，用于行程规划时补出发城市——「下次直接说去哪别再傻问」）"""
    for p in reversed(get_preferences("常驻城市", session_id=session_id)):
        return p["content"]
    return None


def get_common_destinations(n: int = 3, *, session_id: str = "default") -> list[str]:
    """常用目的地（从历史行程统计，「出差习惯」）"""
    its = get_itineraries(session_id=session_id)
    cities: list[str] = []
    for i in its:
        c = i.get("to_city")
        if isinstance(c, str) and c not in ("待定", "未知"):
            cities.append(c)
    return [c for c, _ in Counter(cities).most_common(n)]


# ---------- 长期记忆：历史行程 ----------
def add_itinerary(facts: dict, summary: str, *, session_id: str = "default") -> dict:
    return _get_backend().add_itinerary(session_id, facts, summary)


def get_itineraries(*, session_id: str = "default") -> list[dict]:
    return _get_backend().get_itineraries(session_id)
