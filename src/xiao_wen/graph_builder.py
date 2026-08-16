"""主管图工厂（深模块）：从注册表 manifest 组装产品 LangGraph 图

单一入口 build_supervisor_graph() -> CompiledGraph（单意图单路由 + 多意图并行）：
- 节点 = 懒加载子 Agent 代理 + p_* 并行组 + dispatch fan-out + merge fan-in
- 单意图（subtasks 空）走字符串路由直达子 Agent；多意图走 Send fan-out / merge fan-in

热插拔语义（指纹缓存）：
- 每次 build 重新 discover()（AST 扫描，实测单次 0.48ms）并取意图名序列为指纹
- 指纹命中缓存 → 直接返回已编译图；指纹变化（新子 Agent 落盘/删除）
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
from xiao_wen.eval.trace import AGENT_OUT_KEYS
from xiao_wen.intent import SubTask
from xiao_wen.plugin_registry import discover, load_agent

# ---- State（统一：并行字段可空，单意图图不填即不触发并行路径） ----


def _first_non_none(a: dict | None, b: dict | None) -> dict | None:
    """结构化归约器（plan/stats/history）：单意图直写与并行 merge 都可能写，取第一个非空（主导意图优先）"""
    return a if a is not None else b


def _first_non_empty(a: dict | None, b: dict | None) -> dict | None:
    """upstream 归约器：collect 节点写入（图上只跑一次，无并发写）。
    注意：dict 无 None 联合时缺失字段 current 为 {}（非 None），须用真值判断而非 is not None。"""
    return a if a else b


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
    plan: NotRequired[Annotated[dict | None, _first_non_none]]  # 结构化行程（行程 Agent 产出；非行程为 None）
    stats: NotRequired[Annotated[dict | None, _first_non_none]]  # 差旅画像（差旅统计 Agent 产出；非统计为 None）
    history: NotRequired[Annotated[dict | None, _first_non_none]]  # 历史查询结构化结果（非历史查询为 None）
    sources: NotRequired[list[dict]]  # RAG 来源（知识问答/行程主动知识）
    clarify: NotRequired[bool]  # 消歧门：命中歧义时 True，answer=反问问题，路由短路到 END
    upstream: NotRequired[Annotated[dict, _first_non_empty]]  # collect-then-compose：collect 节点写入，行程 agent 读取


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


def _make_classify(recorder=None):
    """classify_intent 的 trace 包装：评测 recorder 注入时记录 classify 事件（subtasks 序列化）。"""

    def node(state):
        out = classify_intent(state)
        if recorder is not None:
            recorder.record(
                {
                    "type": "classify",
                    "intent": out["intent"],
                    "reason": out["reason"],
                    "subtasks": [s.intent for s in out["subtasks"]],
                }
            )
        return out

    return node


# ---- 懒加载代理节点（派发到该意图时才加载子 Agent 模块） ----
def _make_node(intent_name: str, recorder=None):
    def node(state):
        out = load_agent(intent_name).run(state)
        if recorder is not None and isinstance(out, dict):
            recorder.record(
                {
                    "type": "agent",
                    "agent": intent_name,
                    "out": {k: out.get(k) for k in AGENT_OUT_KEYS if k in out},
                }
            )
        return out

    return node


# ---- 并行组件（导出：纯逻辑可独立测试；由 build_supervisor_graph 组装） ----

# 结构化输出键（图 State / 并行收集 / merge / 会话结果提取共用单一来源）
STRUCTURED_OUTPUT_KEYS = ("plan", "stats", "history")

# 来源是可选扩展字段；仅在 Agent 实际返回时写入，保持旧并行节点输出兼容。
OPTIONAL_OUTPUT_KEYS = ("sources",)


def make_parallel(agent):
    """把原子子 Agent 包成并行节点：读 Send 分支的 current_task，输出 collected（不覆盖 answer）"""

    def node(state):
        sub = state["current_task"]
        out = agent({**state, "user_input": sub.text})
        item = {"intent": sub.intent, "text": sub.text, "answer": out["answer"]}
        item.update({k: out.get(k) for k in STRUCTURED_OUTPUT_KEYS})
        for key in OPTIONAL_OUTPUT_KEYS:
            if key in out:
                item[key] = out[key]
        return {"collected": [item]}

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
            "upstream": state.get("upstream", {}),  # collect-then-compose：行程分支读黑板
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


def _needs_collect(state) -> bool:
    """collect-then-compose 触发条件：主导意图或任一子任务为行程规划"""
    if state.get("intent") == "行程规划":
        return True
    return any(s.intent == "行程规划" for s in state.get("subtasks", []))


def _make_router(*, after_collect: bool = False):
    """统一路由决策（clarify_gate 与 collect_upstream 后的条件边共用）：

    1. 消歧命中 → __clarify_end__（短路反问）
    2. 尚未 collect 且含行程规划 → collect_upstream（collect-then-compose）
    3. dispatch（subtasks 非空 fan-out，否则单路由字符串）
    """

    def route(state):
        if state.get("clarify"):
            return "__clarify_end__"
        if not after_collect and _needs_collect(state):
            return "collect_upstream"
        return dispatch(state)

    return route


def merge(state):
    parts = state["collected"]
    lines = [f"⚡ 同时为你处理了 {len(parts)} 个请求：", ""]
    for p in parts:
        lines.append(f"【{p['intent']}】{p['text']}")
        lines.append(p["answer"])
        lines.append("")
    # 结构化输出：多路结果取第一个非空（主导意图优先，其余分支通常无该字段）
    result: dict[str, str | None] = {"answer": "\n".join(lines)}
    for k in STRUCTURED_OUTPUT_KEYS:
        result[k] = next((p.get(k) for p in parts if p.get(k)), None)
    return result


# ---- 指纹缓存（热插拔：manifest 变化自动重建） ----
# STRUCT_VERSION：图结构版本（collect-then-compose 等结构性改动不改变 manifest 指纹，
# 必须手动升版本让缓存失效重建——否则热插拔复用旧图，结构改动不生效）
STRUCT_VERSION = 2

_cache: dict[tuple[tuple[str, ...], int], CompiledStateGraph] = {}


def build_supervisor_graph(recorder=None) -> CompiledStateGraph:
    """从当前注册表 manifest 组装产品图；指纹缓存保证热插拔运行时生效。

    recorder（评测 trace）：运行时对象，带它时绕过指纹缓存直连组装（不污染生产缓存）。
    """
    manifest = discover()
    fingerprint = tuple(m["INTENT"] for m in manifest)
    key = (fingerprint, STRUCT_VERSION)
    if recorder is not None:
        return _assemble(manifest, recorder)
    if key in _cache:
        return _cache[key]
    _cache.clear()  # manifest 变了：旧指纹的图都过期，一次只留最新一代
    intent.set_intents(manifest)  # 意图词汇表随重建刷新（内部 cache_clear → 模型缓存失效）
    app = _assemble(manifest)
    _cache[key] = app
    return app


def _make_collect():
    """collect-then-compose 收集节点：确定性收集上游（政策/历史/偏好）写入黑板 upstream。

    模块属性访问（itinerary_agent.collect_upstream）便于测试 monkeypatch。
    """

    def node(state):
        from xiao_wen.agents import itinerary_agent

        try:
            upstream = itinerary_agent.collect_upstream(
                state["user_input"],
                state.get("session_id", "default"),
                state.get("recent", ""),
            )
        except TypeError:
            # 兼容旧适配器的二参数收集接缝；正式实现使用 recent 支持多轮城市识别。
            upstream = itinerary_agent.collect_upstream(state["user_input"], state.get("session_id", "default"))
        return {"upstream": upstream}

    return node


def _assemble(manifest: list[dict], recorder=None) -> CompiledStateGraph:
    graph = StateGraph(State)
    graph.add_node("classify_intent", _make_classify(recorder))
    graph.add_node("collect_upstream", _make_collect())
    routes: dict[str, str] = {}
    for m in manifest:
        graph.add_node(m["INTENT"], _make_node(m["INTENT"], recorder))
        routes[m["INTENT"]] = m["INTENT"]
        graph.add_node(f"p_{m['INTENT']}", make_parallel(_make_node(m["INTENT"], recorder)))

    graph.add_node(merge)

    graph.add_edge(START, "classify_intent")
    graph.add_node("clarify_gate", clarify_gate)
    graph.add_edge("classify_intent", "clarify_gate")
    # dict[str, str] 是 dict[Hashable, str] 的合法子集（str 即 Hashable），dict 泛型不变导致需要豁免
    # {**routes, "__clarify_end__": END} 的字面量类型推断为 dict[str, str | object] → 一并豁免
    graph.add_conditional_edges(
        "clarify_gate",
        _make_router(),
        {**routes, "collect_upstream": "collect_upstream", "__clarify_end__": END},  # type: ignore[dict-item]
    )  # type: ignore[arg-type]
    graph.add_conditional_edges(
        "collect_upstream",
        _make_router(after_collect=True),
        {**routes, "__clarify_end__": END},  # type: ignore[dict-item]
    )  # type: ignore[arg-type]
    for name in routes:
        graph.add_edge(f"p_{name}", "merge")
    graph.add_edge("merge", END)
    for name in routes:
        graph.add_edge(name, END)
    return graph.compile()
