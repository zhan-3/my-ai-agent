"""会话闭环：线程状态、主管 Agent Loop、持久化与统一事件流。"""

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, contextmanager, nullcontext, suppress
from dataclasses import dataclass, field
from typing import Any

from xiao_wen import memory
from xiao_wen.agent_loop import AgentLoop
from xiao_wen.contract import (
    HistoryResult,
    KnowledgeSource,
    TravelStats,
    TripPlan,
    history_or_none,
    plan_or_none,
    stats_or_none,
)


@dataclass
class ChatResult:
    answer: str
    intent: str
    reason: str
    plan: TripPlan | None = None
    stats: TravelStats | None = None
    history: HistoryResult | None = None
    sources: list[KnowledgeSource] = field(default_factory=list)
    policy_status: str | None = None
    failure: "ServiceFailure | None" = None


@dataclass(frozen=True)
class ServiceFailure:
    code: str
    message: str
    retryable: bool = True


_FALLBACK_ANSWER = "（暂无回复，请换个说法再试一次）"


@dataclass
class _SessionEntry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    users: int = 0


class _SessionCoordinator:
    """同步/异步轮次共享线程锁；异步等待不阻塞事件循环。"""

    def __init__(self) -> None:
        self._entries: dict[str, _SessionEntry] = {}
        self._guard = threading.Lock()

    def _reserve(self, session_id: str) -> _SessionEntry:
        with self._guard:
            entry = self._entries.setdefault(session_id, _SessionEntry())
            entry.users += 1
            return entry

    def _forget(self, session_id: str, entry: _SessionEntry) -> None:
        with self._guard:
            entry.users -= 1
            if entry.users == 0 and self._entries.get(session_id) is entry:
                del self._entries[session_id]

    @contextmanager
    def turn(self, session_id: str):
        entry = self._reserve(session_id)
        acquired = False
        try:
            entry.lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            self._forget(session_id, entry)

    async def _acquire_async(self, lock: threading.Lock) -> None:
        while True:
            attempt = asyncio.create_task(asyncio.to_thread(lock.acquire, timeout=0.05))
            try:
                acquired = await asyncio.shield(attempt)
            except asyncio.CancelledError:
                acquired = await asyncio.shield(attempt)
                if acquired:
                    lock.release()
                raise
            if acquired:
                return

    @asynccontextmanager
    async def turn_async(self, session_id: str):
        entry = self._reserve(session_id)
        acquired = False
        try:
            await self._acquire_async(entry.lock)
            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            self._forget(session_id, entry)

    @property
    def active_session_count(self) -> int:
        with self._guard:
            return len(self._entries)


_session_coordinator = _SessionCoordinator()


def _resolve_deps(loop: Any, store: Any, cancelled: Callable[[], bool] | None = None) -> tuple[Any, Any]:
    return loop or AgentLoop(cancelled=cancelled or (lambda: False)), store or memory


def _prepare_turn(text: str, session_id: str, user_id: str, store: Any) -> tuple[dict[str, Any], str, dict | None]:
    from xiao_wen.dialogue import load_active_task
    from xiao_wen.memory import get_latest_trip

    recent = store.format_recent_messages(6, session_id=session_id)
    active_task = load_active_task(store, session_id, user_id)
    latest_trip = None
    with suppress(Exception):
        # memory 层的 session_id 参数语义是 user_id（行程/偏好按用户隔离，不按线程隔离）
        latest_trip = get_latest_trip(session_id=user_id)
    return (
        {
            "user_input": text,
            "recent": recent,
            "session_id": session_id,
            "user_id": user_id,
            "active_task": active_task,
            "latest_trip": latest_trip,
        },
        recent,
        active_task,
    )


def _result_from_state(state: dict[str, Any]) -> ChatResult:
    answer = state.get("answer") or _FALLBACK_ANSWER
    failure_data = state.get("failure")
    failure = ServiceFailure(**failure_data) if isinstance(failure_data, dict) else None
    raw_sources = state.get("sources") or []
    return ChatResult(
        answer=answer,
        intent=state.get("intent", ""),
        reason=state.get("reason", ""),
        plan=plan_or_none(state.get("plan")),
        stats=stats_or_none(state.get("stats")),
        history=history_or_none(state.get("history")),
        sources=[KnowledgeSource.model_validate(item) for item in raw_sources if isinstance(item, dict)],
        policy_status=state.get("policy_status"),
        failure=failure,
    )


def service_error_event(failure: ServiceFailure | None = None) -> dict[str, Any]:
    failure = failure or ServiceFailure(
        code="service_unavailable",
        message="⚠️ 服务暂时不可用，请稍后再试。",
    )
    return {
        "type": "error",
        "code": failure.code,
        "message": failure.message,
        "retryable": failure.retryable,
        "policy_status": "unavailable" if failure.code == "policy_unavailable" else None,
    }


def _commit_turn(
    text: str,
    state: dict[str, Any],
    result: ChatResult,
    session_id: str,
    user_id: str,
    store: Any,
) -> None:
    for write in state.get("memory_writes") or []:
        if write.get("type") == "preference":
            store.add_or_update_preference(
                write["category"],
                write["content"],
                write.get("is_update", False),
                session_id=user_id,
            )
        elif write.get("type") == "trip":
            store.save_trip(
                write["facts"],
                write["plan"],
                session_id=user_id,
                thread_id=write.get("thread_id"),
                trip_id=write.get("trip_id"),
                status=write.get("status", "upcoming"),
            )
        elif write.get("type") == "itinerary":
            store.add_itinerary(write["facts"], write["summary"], session_id=user_id)
        else:
            raise ValueError("未知延迟记忆写入")
    transcript = state.get("transcript")
    add_transcript = getattr(store, "add_agent_transcript", None)
    if add_transcript and isinstance(transcript, list):
        add_transcript(transcript, session_id=session_id)
    store.add_message("user", text, session_id=session_id)
    store.add_message("assistant", result.answer, session_id=session_id)


def _finish_turn(
    text: str,
    state: dict[str, Any],
    active_task: dict | None,
    session_id: str,
    user_id: str,
    store: Any,
) -> ChatResult:
    from xiao_wen.dialogue import apply_task_update

    result = _result_from_state(state)
    transaction = getattr(store, "transaction", None)
    with transaction() if transaction else nullcontext():
        if result.failure is None:
            state = apply_task_update(
                state,
                active_before=active_task,
                thread_id=session_id,
                user_id=user_id,
                store=store,
            )
            result = _result_from_state(state)
            _commit_turn(text, state, result, session_id, user_id, store)
    return result


def chat(
    text: str,
    session_id: str = "default",
    *,
    user_id: str | None = None,
    loop: Any = None,
    store: Any = None,
) -> ChatResult:
    """同步执行一轮 Agent Loop；成功后原子完成会话层写回。"""
    user_id = user_id or session_id
    with _session_coordinator.turn(session_id):
        runner, store = _resolve_deps(loop, store)
        turn, _, active_task = _prepare_turn(text, session_id, user_id, store)
        state = runner.run(turn)
        return _finish_turn(text, state, active_task, session_id, user_id, store)


def _stage_event(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("type") == "run_start":
        return {"type": "stage", "status": "start"}
    if event.get("type") == "agent_start":
        return {"type": "stage", "status": "working", "intent": event.get("agent", "")}
    if event.get("type") == "agent_result":
        return {"type": "stage", "status": "done", "intent": event.get("agent", "")}
    return None


async def stream_chat(
    text: str,
    session_id: str = "default",
    *,
    user_id: str | None = None,
    loop: Any = None,
    store: Any = None,
) -> AsyncIterator[dict[str, Any]]:
    """异步转发同一 Agent Loop 的生命周期事件；取消时不提交会话结果。"""
    user_id = user_id or session_id
    async with _session_coordinator.turn_async(session_id):
        cancelled = threading.Event()
        runner, store = _resolve_deps(loop, store, cancelled.is_set)
        turn, _, active_task = _prepare_turn(text, session_id, user_id, store)
        event_loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def emit(event: dict[str, Any]) -> None:
            event_loop.call_soon_threadsafe(queue.put_nowait, event)

        task = asyncio.create_task(asyncio.to_thread(runner.run, turn, emit))
        try:
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05)
                except TimeoutError:
                    continue
                stage = _stage_event(event)
                if stage:
                    yield stage
            state = await task
        except (asyncio.CancelledError, GeneratorExit):
            cancelled.set()
            with suppress(Exception):
                await asyncio.shield(task)
            raise
        except Exception as error:
            from xiao_wen.stability import logger

            logger.error("stream_chat 失败（session=%s）：%s", session_id, error)
            yield service_error_event()
            return

        result = _finish_turn(text, state, active_task, session_id, user_id, store)
        if result.failure is not None:
            yield service_error_event(result.failure)
            return
        yield {
            "type": "done",
            "answer": result.answer,
            "intent": result.intent,
            "reason": result.reason,
            "plan": result.plan.model_dump() if result.plan else None,
            "stats": result.stats.model_dump() if result.stats else None,
            "history": result.history.model_dump() if result.history else None,
            "sources": [source.model_dump() for source in result.sources],
            "policy_status": result.policy_status,
        }
