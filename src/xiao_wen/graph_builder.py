"""主管图工厂（深模块）：从注册表 manifest 组装主管/调度 LangGraph 图

单一入口 build_supervisor_graph(parallel) -> CompiledGraph：
- parallel=False 单意图主管图（节点 = 懒加载子 Agent 代理，条件边 = manifest 意图字符串路由）
- parallel=True 调度图（在主管图基础上增加 p_* 并行组 + dispatch fan-out + merge fan-in，
  State 增加 subtasks/current_task/collected 并行字段；单意图路径完全不变）

热插拔语义（指纹缓存）：
- 每次 build 重新 discover()（AST 扫描，实测单次 0.48ms）并取意图名序列为指纹
- 指纹 + parallel 参数命中缓存 → 直接返回已编译图；指纹变化（新子 Agent 落盘/删除）
  → 自动重建——与 intent.set_intents 的 cache_clear 同理：两层注入都自动失效，
  不需要 importlib.reload 的模块级副作用（ADR-0005 注册表驱动语义的收口）

组装顺序是产品行为，勿改：先 classify_intent（意图分类 + 多意图拆分）→
条件路由（subtasks 非空走 Send fan-out，否则字符串路由）→ 子 Agent 节点 / 并行组。
"""

import operator
from typing import Annotated, NotRequired, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from xiao_wen import disambiguation, intent
from xiao_wen.intent import SubTask
from xiao_wen.plugin_registry import discover, load_agent

# ---- State（统一：并行字段可空，单意图图不填即不触发并行路径） ----


def _first_plan(a: dict | None, b: dict | None) -> dict | None:
    """plan 归约器：单意图直写与并行 merge 都可能写 plan，取第一个非空（主导意图优先）"""
    return a if a is not None else b


def _first_stats(a: dict | None, b: dict | None) -> dict | None:
    """stats 归约器：同 plan（差旅统计分支产出画像数据，取第一个非空）"""
    return a if a is not None else b


def _first_history(a: dict | None, b: dict | None) -> dict | None:
    """history 归约器：同 stats（历史查询分支产出结构化行程，取第一个非空）"""
    return a if a is not None else b


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    recent: str  # 短期记忆：最近对话（每轮 invoke 前注入）
    intent: str
    reason: str
    answer: str
    subtasks: NotRequired[list[SubTask]]  # 多意图拆分子任务（单意图时为空数组）
    current_task: NotRequired[SubTask]  # Send 分支内当前子任务
    collected: NotRequired[Annotated[list[dict], operator.add]]  # 并行结果收集（归约器拼接）
    session_id: NotRequired[str]  # 会话维度（记忆隔离；未传时 agent 兑底 "default"）
    plan: NotRequired[Annotated[dict | None, _first_plan]]  # 结构化行程（行程 Agent 产出；非行程为 None）
    stats: NotRequired[Annotated[dict | None, _first_stats]]  # 差旅画像（差旅统计 Agent 产出；非统计为 None）
    history: NotRequired[Annotated[dict | None, _first_history]]  # 历史查询结构化结果（非历史查询为 None）
    clarify: NotRequired[bool]  # 消歧门：命中歧义时 True，answer=反问问题，路由短路到 END


# ---- 分类节点（唯一实现：恒返回 subtasks，由 parallel 参数决定是否使用） ----
def classify_intent(state):
    r = intent.classify(state["recent"], state["user_input"])
    # 兜底：LLM 幻觉意图不在词汇表内 → 归「其他」（避免路由 KeyError）
    return {"intent": r.intent, "reason": r.reason, "subtasks": r.subtasks}


# ---- 消歧门（轻量消歧：意图层真歧义 → 带选项反问，命中短路到 END） ----
def clarify_gate(state):
    """classify 之后、路由之前：纯规则判定歧义；命中则 answer=反问/直答并短路"""
    q = disambiguation.clarify(state["user_input"], state["intent"], state.get("recent", ""))
    if q:
        return {"clarify": True, "answer": q}
    return {"clarify": False}


# ---- 懒加载代理节点（派发到该意图时才加载子 Agent 模块） ----
def _make_node(intent_name: str):
    def node(state):
        return load_agent(intent_name).run(state)

    return node


# ---- 并行组件（导出：纯逻辑可独立测试；由 build_supervisor_graph 组装） ----


def make_parallel(agent):
    """把原子子 Agent 包成并行节点：读 Send 分支的 current_task，输出 collected（不覆盖 answer）"""

    def node(state):
        sub = state["current_task"]
        out = agent({**state, "user_input": sub.text})
        return {
            "collected": [
                {
                    "intent": sub.intent,
                    "text": sub.text,
                    "answer": out["answer"],
                    "plan": out.get("plan"),
                    "stats": out.get("stats"),
                    "history": out.get("history"),
                }
            ]
        }

    return node


def dispatch(state):
    """fan-out 条件边函数：多意图 → Send 列表（并行执行）；单意图 → 字符串路由

    主导意图兜底：LLM 有时只把次要请求放进 subtasks、漏掉主导意图
    （如「帮我安排行程，喜欢住连锁酒店」→ subtasks 仅含偏好记录），
    此时用完整输入补一条主导意图分支，避免主导意图被静默丢弃。
    """
    subs = state.get("subtasks")
    if subs:
        # 并行分支必须继承上文（recent/session_id）：否则子 Agent 只看 current_task.text，
        # 提取模型拿不到上轮要素（如补全轮丢了目的城市/日期）——续接失效的根因
        ctx = {
            "recent": state.get("recent", ""),
            "session_id": state.get("session_id", "default"),
            "messages": state.get("messages", []),
        }
        sends: list[Send] = []
        primary = state["intent"]
        if not any(s.intent == primary for s in subs):
            sends.append(
                Send(
                    f"p_{primary}",
                    {"current_task": SubTask(intent=primary, text=state["user_input"]), **ctx},
                )
            )
        sends.extend(Send(f"p_{s.intent}", {"current_task": s, **ctx}) for s in subs)
        return sends
    return state["intent"]


def route_after_gate(state):
    """消歧门条件边（并行图）：命中 → 短路 END；未命中 → 原 dispatch fan-out 不变"""
    if state.get("clarify"):
        return "__clarify_end__"
    return dispatch(state)


def route_after_gate_serial(state):
    """消歧门条件边（单意图图）：命中 → 短路 END；未命中 → 原字符串路由不变"""
    if state.get("clarify"):
        return "__clarify_end__"
    return state["intent"]


def merge(state):
    parts = state["collected"]
    lines = [f"⚡ 同时为你处理了 {len(parts)} 个请求：", ""]
    for p in parts:
        lines.append(f"【{p['intent']}】{p['text']}")
        lines.append(p["answer"])
        lines.append("")
    # 结构化 plan：多路结果取第一个非空（主导意图优先，其余分支通常无 plan）
    plan = next((p.get("plan") for p in parts if p.get("plan")), None)
    # 结构化 stats：同上（差旅统计分支产出画像数据，前端渲染卡片）
    stats = next((p.get("stats") for p in parts if p.get("stats")), None)
    # 结构化 history：同上（历史查询分支产出结构化行程，前端渲染卡片）
    history = next((p.get("history") for p in parts if p.get("history")), None)
    return {"answer": "\n".join(lines), "plan": plan, "stats": stats, "history": history}


# ---- 指纹缓存（热插拔：manifest 变化自动重建） ----
_cache: dict[tuple[tuple[str, ...], bool], CompiledStateGraph] = {}


def build_supervisor_graph(parallel: bool = False) -> CompiledStateGraph:
    """从当前注册表 manifest 组装主管图；指纹缓存保证热插拔运行时生效。"""
    manifest = discover()
    fingerprint = tuple(m["INTENT"] for m in manifest)
    key = (fingerprint, parallel)
    if key in _cache:
        return _cache[key]
    _cache.clear()  # manifest 变了：旧指纹的图都过期，一次只留最新一代
    intent.set_intents(manifest)  # 意图词汇表随重建刷新（内部 cache_clear → 模型缓存失效）
    app = _assemble(manifest, parallel)
    _cache[key] = app
    return app


def _assemble(manifest: list[dict], parallel: bool) -> CompiledStateGraph:
    graph = StateGraph(State)
    graph.add_node(classify_intent)
    routes: dict[str, str] = {}
    for m in manifest:
        graph.add_node(m["INTENT"], _make_node(m["INTENT"]))
        routes[m["INTENT"]] = m["INTENT"]
        if parallel:
            graph.add_node(f"p_{m['INTENT']}", make_parallel(_make_node(m["INTENT"])))

    if parallel:
        graph.add_node(merge)

    graph.add_edge(START, "classify_intent")
    graph.add_node("clarify_gate", clarify_gate)
    graph.add_edge("classify_intent", "clarify_gate")
    if parallel:
        # dict[str, str] 是 dict[Hashable, str] 的合法子集（str 即 Hashable），dict 泛型不变导致需要豁免
        # {**routes, "__clarify_end__": END} 的字面量类型推断为 dict[str, str | object] → 一并豁免
        graph.add_conditional_edges("clarify_gate", route_after_gate, {**routes, "__clarify_end__": END})  # type: ignore[arg-type, dict-item]
        for name in routes:
            graph.add_edge(f"p_{name}", "merge")
        graph.add_edge("merge", END)
    else:
        graph.add_conditional_edges("clarify_gate", route_after_gate_serial, {**routes, "__clarify_end__": END})  # type: ignore[arg-type, dict-item]
    for name in routes:
        graph.add_edge(name, END)
    return graph.compile()
