"""会话循环模块：一轮完整交互的闭环（ADR-0002，取代 webapp/system/scheduler 三处复制）

- chat(text, session_id) -> ChatResult(answer, intent, reason, plan, stats, history)
  读最近对话（短期记忆）→ 注入 → 主管图 invoke → 写回用户与助手两轮
- 异常向上抛：降级文案是 Web 层的职责（webapp 保留 try/except）
- 依赖可注入：graph 默认产品图（build_supervisor_graph()，单意图单路由 + 多意图并行）；
  store 默认 memory 模块（假图/假存储即可测循环）
- 对话隔离：线程 transcript/活跃任务按 session_id，长期记忆按 user_id（ADR-0009）
- 结构化字段（plan/stats/history）在本层统一校验为契约模型（contract）——图产出 dict
  只在此处降级一次，webapp / SSE 直接消费模型，不再重复校验
"""

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field

from xiao_wen import memory
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
    plan: TripPlan | None = None  # 结构化行程（契约模型；图 dict 已在此层校验/降级）
    stats: TravelStats | None = None  # 差旅画像（契约模型；同上）
    history: HistoryResult | None = None  # 历史查询结构化结果（契约模型；同上）
    sources: list[KnowledgeSource] = field(default_factory=list)  # RAG 证据来源
    policy_status: str | None = None
    failure: "ServiceFailure | None" = None


@dataclass(frozen=True)
class ServiceFailure:
    code: str
    message: str
    retryable: bool = True


# 防御：任何 Agent 返回空/缺失 answer 时的兜底文案（LLM 偶发 None/空串）
_FALLBACK_ANSWER = "（暂无回复，请换个说法再试一次）"


@dataclass
class _SessionEntry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    users: int = 0


class _SessionCoordinator:
    """单进程会话协调：同步与异步轮次共享锁，等待不阻塞事件循环，空闲项自动回收。"""

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


def _resolve_deps(graph, store, recorder=None):
    """图与存储的懒构造/注入：默认调度图 + 默认 memory（chat 与 stream_chat 共用）"""
    if graph is None:
        from xiao_wen.graph_builder import build_supervisor_graph

        graph = build_supervisor_graph() if recorder is None else build_supervisor_graph(recorder=recorder)
    if store is None:
        store = memory
    return graph, store


def _prepare_turn(text: str, session_id: str, user_id: str, store):
    """读短期记忆 + 组装图输入（chat 与 stream_chat 共用）"""
    from xiao_wen.dialogue import load_active_task

    recent = store.format_recent_messages(6, session_id=session_id)
    active_task = load_active_task(store, session_id, user_id)
    state_in = {
        "messages": [("human", text)],
        "user_input": text,
        "recent": recent,
        "session_id": session_id,
        "user_id": user_id,
        "active_task": active_task,
    }
    return state_in, recent, active_task


def _result_from_state(state: dict) -> ChatResult:
    """图输出 dict → ChatResult：answer 兜底 + 结构化字段契约校验（单一降级点）"""
    answer = state.get("answer") or _FALLBACK_ANSWER
    failure_data = state.get("failure")
    failure = ServiceFailure(**failure_data) if isinstance(failure_data, dict) else None
    return ChatResult(
        answer=answer,
        intent=state.get("intent", ""),
        reason=state.get("reason", ""),
        plan=plan_or_none(state.get("plan")),
        stats=stats_or_none(state.get("stats")),
        history=history_or_none(state.get("history")),
        sources=[KnowledgeSource.model_validate(item) for item in (state.get("sources") or [])],
        policy_status=state.get("policy_status"),
        failure=failure,
    )


def service_error_event(failure: ServiceFailure | None = None) -> dict:
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


def _commit_turn(text: str, answer: str, session_id: str, store) -> None:
    """写回用户与助手两轮（chat 与 stream_chat 共用，顺序一致）"""
    store.add_message("user", text, session_id=session_id)
    store.add_message("assistant", answer, session_id=session_id)


def _record_final(recorder, state: dict, result: ChatResult) -> None:
    if recorder is None:
        return
    recorder.record(
        {
            "type": "final",
            "intent": state.get("intent", ""),
            "reason": state.get("reason", ""),
            "answer": result.answer,
            "plan": state.get("plan"),
            "stats": state.get("stats"),
            "history": state.get("history"),
            "sources": [source.model_dump() for source in result.sources],
            "policy_status": result.policy_status,
            "failure": result.failure.__dict__ if result.failure else None,
        }
    )


def chat(
    text: str,
    session_id: str = "default",
    *,
    user_id: str | None = None,
    graph=None,
    store=None,
    recorder=None,
) -> ChatResult:
    """一轮对话闭环。

    - graph：默认调度图（懒导入 graph_builder，走指纹缓存；多意图并行走 Send fan-out）
    - store：默认 xiao_wen.memory（读 recent / 写回两轮）；可注入假存储
    - session_id：短期 transcript 与活跃任务的线程维度
    - user_id：长期偏好/历史所有者；省略时兼容使用 session_id
    - recorder：显式观察模式在 recent/final/memory_write 三处记录事件；默认 None 零开销
    """
    user_id = user_id or session_id
    with _session_coordinator.turn(session_id):
        graph, store = _resolve_deps(graph, store, recorder)
        state_in, recent, active_task = _prepare_turn(text, session_id, user_id, store)
        if recorder is not None:
            recorder.record({"type": "recent", "recent": recent})
        r = graph.invoke(state_in)
        from xiao_wen.dialogue import apply_task_update

        r = apply_task_update(
            r,
            active_before=active_task,
            thread_id=session_id,
            user_id=user_id,
            store=store,
        )
        result = _result_from_state(r)
        if result.failure is None:
            _commit_turn(text, result.answer, session_id, store)
        _record_final(recorder, r, result)
        if recorder is not None and result.failure is None:
            recorder.record({"type": "memory_write", "user": text, "assistant": result.answer})
    return result


async def stream_chat(
    text: str,
    session_id: str = "default",
    *,
    user_id: str | None = None,
    graph=None,
    store=None,
    recorder=None,
) -> AsyncIterator[dict]:
    """流式会话循环（SSE 阶段事件）：与 chat() 同一条图、同一记忆闭环，但逐个产出事件：

    - {"type": "stage", "status": "start"}                           请求已受理
    - {"type": "stage", "status": "intent", "intent": "行程规划"}    意图已解析（classify 完成）
    - {"type": "stage", "status": "working", "intent": "X"}        子 Agent 开始
    - {"type": "stage", "status": "done", "intent": "X"}          子 Agent 完成
    - {"type": "stage", "status": "done", "intent": "__merge__"}   并行汇总完成
    - {"type": "done", "answer": ..., "intent": ..., "reason": ..., "plan": ...}
    - {"type": "error", "message": ...}                               异常降级（不中断流）

    实现：graph.astream_events(stream_mode="values") 监听节点自身事件
    （name == langgraph_node 过滤嵌套链），chunk 按节点累积还原最终 state。
    记忆写回在流结束、done 之前（与 chat() 语义一致）。
    """
    user_id = user_id or session_id
    async with _session_coordinator.turn_async(session_id):
        graph, store = _resolve_deps(graph, store, recorder)
        state_in, recent, active_task = _prepare_turn(text, session_id, user_id, store)
        if recorder is not None:
            recorder.record({"type": "recent", "recent": recent})
        yield {"type": "stage", "status": "start"}
        final: dict | None = None
        try:
            async for ev in graph.astream_events(state_in, version="v2", stream_mode="values"):
                node = ev.get("metadata", {}).get("langgraph_node")
                if not node or ev.get("name") != node:  # 只认节点自身事件（嵌套链 name 不同）
                    continue
                etype = ev["event"]
                if etype == "on_chain_start":
                    stage = _stage_event(node, "working")
                    if stage:
                        yield stage
                elif etype == "on_chain_end":
                    stage = _stage_event(node, "done")
                    if stage:
                        yield stage
                    out = ev.get("data", {}).get("output")
                    if isinstance(out, dict):
                        # 普通函数节点不产生 stream chunk，其写入（如行程 plan）在 output 里
                        final = {**(final or {}), **out}
                elif etype == "on_chain_stream":
                    chunk = ev.get("data", {}).get("chunk")
                    if chunk is None:
                        continue
                    final = {**(final or {}), **chunk}  # values 模式 chunk 只含本节点写入，逐节点累积
                    if node == "classify_intent" and chunk.get("intent"):
                        yield {"type": "stage", "status": "intent", "intent": chunk["intent"]}
        except Exception as e:  # LLM 熔断/网络异常：降级事件而非整个流崩溃
            from xiao_wen.stability import logger

            logger.error("stream_chat 失败（session=%s）：%s", session_id, e)
            if recorder is not None:
                recorder.record({"type": "error", "code": "service_unavailable", "message": str(e)})
            yield service_error_event()
            return
        if final is None:  # 防御：图没产出任何 state
            if recorder is not None:
                recorder.record({"type": "error", "code": "empty_state"})
            yield service_error_event()
            return
        from xiao_wen.dialogue import apply_task_update

        final = apply_task_update(
            final,
            active_before=active_task,
            thread_id=session_id,
            user_id=user_id,
            store=store,
        )
        result = _result_from_state(final)
        _record_final(recorder, final, result)
        if result.failure is not None:
            yield service_error_event(result.failure)
            return
        _commit_turn(text, result.answer, session_id, store)
        if recorder is not None:
            recorder.record({"type": "memory_write", "user": text, "assistant": result.answer})
        yield {
            "type": "done",
            "answer": result.answer,
            "intent": result.intent,
            "reason": result.reason,
            # SSE 由 json.dumps 手写序列化：plan / stats / history 输出 dict（与 POST /api/chat 响应体一致）
            "plan": result.plan.model_dump() if result.plan else None,
            "stats": result.stats.model_dump() if result.stats else None,
            "history": result.history.model_dump() if result.history else None,
            "sources": [source.model_dump() for source in result.sources],
            "policy_status": result.policy_status,
        }


def _stage_event(node: str, status: str) -> dict | None:
    """节点名 → 阶段事件：p_* 并行分支剥前缀；merge 用 __merge__ 占位；
    classify_intent 是内部节点（有专门的 intent 事件），不暴露"""
    if node == "classify_intent" or node == "clarify_gate":
        return None
    if node == "merge":
        intent = "__merge__"
    elif node.startswith("p_"):
        intent = node[2:]
    else:
        intent = node
    return {"type": "stage", "status": status, "intent": intent}
