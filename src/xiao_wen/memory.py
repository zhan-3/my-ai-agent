"""记忆模块：短期 + 长期两层记忆（存储后端协议：InMemory 演示兜底 / Postgres 产品后端）

- 会话隔离：所有记忆按 session_id 隔离（默认 "default"，向后兼容既有调用点）
- 后端协议 MemoryBackend：三个域（消息/偏好/行程）的按 session 读写；
  InMemoryBackend（进程内存，无 POSTGRES_URL 时的演示/测试兜底）与
  PostgresBackend（memory_pg.py，psycopg，POSTGRES_URL 时启用）实现同一接口
- 组合函数留在函数层：format_recent_messages / get_home_city / get_common_destinations
  （backend 只管基础读写，组合逻辑不重复）
- 测试注入：set_backend(fresh InMemoryBackend) 替代旧的 MEMORY_PATH monkeypatch
"""

import os
import time
from collections import Counter
from typing import Protocol


class MemoryBackend(Protocol):
    """记忆存储后端协议：三个域（消息/偏好/行程）按 session 的基础读写"""

    def add_message(self, session_id: str, role: str, content: str) -> dict: ...

    def get_recent_messages(self, session_id: str, n: int) -> list[dict]: ...

    def add_or_update_preference(
        self, session_id: str, category: str, content: str, is_update: bool = False
    ) -> dict: ...

    def get_preferences(self, session_id: str, category: str | None = None) -> list[dict]: ...

    def add_itinerary(self, session_id: str, facts: dict, summary: str) -> dict: ...

    def get_itineraries(self, session_id: str) -> list[dict]: ...


class InMemoryBackend:
    """进程内存后端：无 POSTGRES_URL 时的演示/测试兜底（重启即失，README 注明）"""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def _sess(self, session_id: str) -> dict:
        return self._data.setdefault(session_id, {"messages": [], "preferences": [], "itineraries": []})

    def add_message(self, session_id: str, role: str, content: str) -> dict:
        rec = {"role": role, "content": content, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        self._sess(session_id)["messages"].append(rec)
        return rec

    def get_recent_messages(self, session_id: str, n: int) -> list[dict]:
        return self._sess(session_id)["messages"][-n:]

    def add_or_update_preference(self, session_id: str, category: str, content: str, is_update: bool = False) -> dict:
        prefs = self._sess(session_id)["preferences"]
        if is_update:
            prefs[:] = [p for p in prefs if p["category"] != category]
        rec = {"category": category, "content": content, "ts": time.strftime("%Y-%m-%d %H:%M")}
        prefs.append(rec)
        return rec

    def get_preferences(self, session_id: str, category: str | None = None) -> list[dict]:
        prefs = self._sess(session_id)["preferences"]
        if category:
            return [p for p in prefs if p["category"] == category]
        return list(prefs)

    def add_itinerary(self, session_id: str, facts: dict, summary: str) -> dict:
        rec = {**facts, "summary": summary, "ts": time.strftime("%Y-%m-%d %H:%M")}
        self._sess(session_id)["itineraries"].append(rec)
        return rec

    def get_itineraries(self, session_id: str) -> list[dict]:
        return list(self._sess(session_id)["itineraries"])


# ---- 模块级当前后端（测试注入 set_backend；生产惰性按 env 分派） ----
_backend: MemoryBackend | None = None


def set_backend(backend: MemoryBackend) -> None:
    """注入存储后端（测试注入全新 InMemoryBackend 隔离；生产由 _get_backend 按 env 分派）"""
    global _backend  # noqa: PLW0603 —— 后端注入是模块级状态的刻意设计
    _backend = backend


def _get_backend() -> MemoryBackend:
    """惰性分派：POSTGRES_URL 时 PostgresBackend（产品持久化），否则 InMemoryBackend（演示兜底）"""
    global _backend  # noqa: PLW0603
    if _backend is None:
        url = os.environ.get("POSTGRES_URL")
        if url:
            from xiao_wen.memory_pg import PostgresBackend  # 懒导入：pg 依赖可选

            _backend = PostgresBackend(url)
        else:
            _backend = InMemoryBackend()
    return _backend


# ---------- 短期记忆：最近 N 轮对话（session 维度） ----------
def add_message(role: str, content: str, *, session_id: str = "default") -> dict:
    return _get_backend().add_message(session_id, role, content)


def get_recent_messages(n: int = 6, *, session_id: str = "default") -> list[dict]:
    """最近 n 条消息（按时间正序）"""
    return _get_backend().get_recent_messages(session_id, n)


def format_recent_messages(n: int = 6, *, session_id: str = "default") -> str:
    """格式化为给 LLM 看的文本（供意图识别注入，hot path 注入要克制）"""
    msgs = get_recent_messages(n, session_id=session_id)
    if not msgs:
        return "无"
    lines = [f"{'用户' if m['role'] == 'user' else '助手'}: {m['content'][:80]}" for m in msgs]
    return "\n".join(lines)


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


if __name__ == "__main__":
    # 自检：短期能存能读；偏好追加/覆盖；常驻城市
    add_message("user", "自检：你好")
    add_message("assistant", "自检：你好，有什么可以帮你？")
    print("recent:", format_recent_messages(4))
    add_or_update_preference("常驻城市", "自检：上海")
    add_or_update_preference("常驻城市", "自检：北京", is_update=True)  # 覆盖
    print("home:", get_home_city())
    print("prefs:", get_preferences())
