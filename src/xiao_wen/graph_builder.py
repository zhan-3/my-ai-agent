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

from xiao_wen import intent
from xiao_wen.intent import SubTask
from xiao_wen.plugin_registry import discover, load_agent


# ---- State（统一：并行字段可空，单意图图不填即不触发并行路径） ----
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


# ---- 分类节点（唯一实现：恒返回 subtasks，由 parallel 参数决定是否使用） ----
def classify_intent(state):
    r = intent.classify(state["recent"], state["user_input"])
    # 兜底：LLM 幻觉意图不在词汇表内 → 归「其他」（避免路由 KeyError）
    return {"intent": r.intent, "reason": r.reason, "subtasks": r.subtasks}


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
        return {"collected": [{"intent": sub.intent, "text": sub.text, "answer": out["answer"]}]}

    return node


def dispatch(state):
    """fan-out 条件边函数：多意图 → Send 列表（并行执行）；单意图 → 字符串路由"""
    subs = state.get("subtasks")
    if subs:
        return [Send(f"p_{s.intent}", {"current_task": s}) for s in subs]
    return state["intent"]


def merge(state):
    parts = state["collected"]
    lines = [f"⚡ 同时为你处理了 {len(parts)} 个请求：", ""]
    for p in parts:
        lines.append(f"【{p['intent']}】{p['text']}")
        lines.append(p["answer"])
        lines.append("")
    return {"answer": "\n".join(lines)}


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
    if parallel:
        # dict[str, str] 是 dict[Hashable, str] 的合法子集（str 即 Hashable），dict 泛型不变导致需要豁免
        graph.add_conditional_edges("classify_intent", dispatch, routes)  # type: ignore[arg-type]
        for name in routes:
            graph.add_edge(f"p_{name}", "merge")
        graph.add_edge("merge", END)
    else:
        graph.add_conditional_edges("classify_intent", lambda s: s["intent"], routes)  # type: ignore[arg-type]
    for name in routes:
        graph.add_edge(name, END)
    return graph.compile()
