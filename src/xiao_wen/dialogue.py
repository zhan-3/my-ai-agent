"""线程级对话状态：分离 transcript、长期记忆所有者和未完成任务。"""

import re
from typing import Any

_CONVERSATION_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_MAX_RESUME_CONTEXT = 4000


def make_thread_id(user_id: str, conversation_id: str) -> str:
    """派生用户作用域内的线程键；客户端不能借 conversation_id 越过用户隔离。"""
    if not _CONVERSATION_ID.fullmatch(conversation_id):
        raise ValueError("conversation_id 格式无效")
    return f"{user_id}:{conversation_id}"


def load_active_task(store: Any, thread_id: str, user_id: str) -> dict | None:
    getter = getattr(store, "get_active_task", None)
    return getter(thread_id=thread_id, user_id=user_id) if getter else None


def focused_recent(active_task: dict | None, fallback: str) -> str:
    """行程续接只看任务自己的聚焦 transcript，不吸入中途插入的无关请求。"""
    if active_task and active_task.get("intent") == "行程规划":
        context = active_task.get("resume_context")
        if isinstance(context, str) and context.strip():
            return context[-_MAX_RESUME_CONTEXT:]
    return fallback


def task_update_set(
    *, resume_context: str, missing: list[str], trip_id: int | None = None, facts: dict | None = None
) -> dict:
    task: dict = {
        "intent": "行程规划",
        "resume_context": resume_context[-_MAX_RESUME_CONTEXT:],
        "missing": list(missing),
    }
    if trip_id is not None:
        task["trip_id"] = trip_id
    if facts:
        task["facts"] = facts
    return {"action": "set", "task": task}


def task_update_clear() -> dict:
    return {"action": "clear"}


def task_update_cancel() -> dict:
    """用户取消：drafting 行程转 cancelled（保留记录不删除，区别于「完成」的 clear）。"""
    return {"action": "cancel"}


def apply_task_update(
    state: dict,
    *,
    active_before: dict | None,
    thread_id: str,
    user_id: str,
    store: Any,
) -> dict:
    """持久化图产出的任务变化，并为不覆盖任务的插入请求追加明确提醒。"""
    update = state.get("task_update")
    setter = getattr(store, "set_active_task", None)
    clearer = getattr(store, "clear_active_task", None)
    canceller = getattr(store, "cancel_active_task", None)
    if isinstance(update, dict) and update.get("action") == "set" and isinstance(update.get("task"), dict):
        if setter:
            setter(update["task"], thread_id=thread_id, user_id=user_id)
        return state
    if isinstance(update, dict) and update.get("action") == "clear":
        if clearer:
            clearer(thread_id=thread_id, user_id=user_id)
        return state
    if isinstance(update, dict) and update.get("action") == "cancel":
        if canceller:
            canceller(thread_id=thread_id, user_id=user_id)
        return state
    if active_before and state.get("intent") != "行程规划":
        missing = [str(item) for item in active_before.get("missing", []) if item]
        detail = "、".join(missing) if missing else "必要信息"
        answer = state.get("answer") or ""
        state = {**state, "answer": f"{answer}\n\n↩️ 刚才的行程仍保留，继续时请补充：{detail}。"}
    return state
