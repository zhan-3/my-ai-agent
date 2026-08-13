"""会话循环模块：一轮完整交互的闭环（ADR-0002，取代 webapp/system/scheduler 三处复制）

- chat(text, session_id) -> ChatResult(answer, intent, reason)
  读最近对话（短期记忆）→ 注入 → 主管图 invoke → 写回用户与助手两轮
- 异常向上抛：降级文案是 web 层的职责（webapp 保留 try/except），demo 需要真实异常
- 依赖可注入：graph 默认调度图（build_supervisor_graph(parallel=True)，多意图并行）；
  store 默认 memory 模块（假图/假存储即可测循环）
- 会话隔离：记忆按 session_id 隔离（ADR-0006），webapp 层升级为用户隔离（ADR-0007）
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from xiao_wen import memory


@dataclass
class ChatResult:
    answer: str
    intent: str
    reason: str
    plan: dict | None = None  # 结构化行程（slice 1：行程 Agent 产出；非行程为 None）


# 防御：任何 Agent 返回空/缺失 answer 时的兜底文案（LLM 偶发 None/空串）
_FALLBACK_ANSWER = "（暂无回复，请换个说法再试一次）"


def chat(text: str, session_id: str = "default", *, graph=None, store=None) -> ChatResult:
    """一轮对话闭环。

    - graph：默认调度图（懒导入 graph_builder，走指纹缓存；多意图并行走 Send fan-out）
    - store：默认 xiao_wen.memory（读 recent / 写回两轮）；可注入假存储
    - session_id：会话维度（webapp 层 = 用户名），记忆按此隔离（ADR-0006 / ADR-0007）
    """
    if graph is None:
        from xiao_wen.graph_builder import build_supervisor_graph

        graph = build_supervisor_graph(parallel=True)
    if store is None:
        store = memory

    recent = store.format_recent_messages(6, session_id=session_id)
    r = graph.invoke(
        {
            "messages": [("human", text)],
            "user_input": text,
            "recent": recent,
            "session_id": session_id,
        }
    )
    store.add_message("user", text, session_id=session_id)
    raw = r.get("answer") if isinstance(r, dict) else getattr(r, "answer", "")
    answer = raw or _FALLBACK_ANSWER
    store.add_message("assistant", answer, session_id=session_id)
    return ChatResult(answer=answer, intent=r["intent"], reason=r["reason"], plan=r.get("plan"))


async def stream_chat(text: str, session_id: str = "default", *, graph=None, store=None) -> AsyncIterator[dict]:
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
    if graph is None:
        from xiao_wen.graph_builder import build_supervisor_graph

        graph = build_supervisor_graph(parallel=True)
    if store is None:
        store = memory

    recent = store.format_recent_messages(6, session_id=session_id)
    state_in = {
        "messages": [("human", text)],
        "user_input": text,
        "recent": recent,
        "session_id": session_id,
    }
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
        yield {"type": "error", "message": "⚠️ 服务暂时不可用，请稍后再试。"}
        return
    if final is None:  # 防御：图没产出任何 state
        yield {"type": "error", "message": "⚠️ 服务暂时不可用，请稍后再试。"}
        return
    from xiao_wen.contract import plan_or_none
    from xiao_wen.stability import logger

    store.add_message("user", text, session_id=session_id)
    answer = final.get("answer") or _FALLBACK_ANSWER
    store.add_message("assistant", answer, session_id=session_id)
    plan = plan_or_none(final.get("plan"))
    yield {
        "type": "done",
        "answer": answer,
        "intent": final.get("intent", ""),
        "reason": final.get("reason", ""),
        # SSE 由 json.dumps 手写序列化：plan 必须输出 dict（与 POST /api/chat 响应体一致）
        "plan": plan.model_dump() if plan else None,
    }


def _stage_event(node: str, status: str) -> dict | None:
    """节点名 → 阶段事件：p_* 并行分支剥前缀；merge 用 __merge__ 占位；
    classify_intent 是内部节点（有专门的 intent 事件），不暴露"""
    if node == "classify_intent":
        return None
    if node == "merge":
        intent = "__merge__"
    elif node.startswith("p_"):
        intent = node[2:]
    else:
        intent = node
    return {"type": "stage", "status": status, "intent": intent}
