"""调度优化模块：同优先级任务并行执行（Send API fan-out/fan-in）
跑法：uv run python -m xiao_wen.scheduler
依赖：xiao_wen.plugin_registry（子 Agent 注册表，懒加载 worker）

设计（对比「固定顺序串行」）：
- 动态路由：按意图选 worker（条件边）
- ★并行执行：一句话含多个独立请求 → 意图识别拆分子任务（subtasks）→
  dispatcher 用 Send 把每个子任务并行派发给对应 worker（fan-out）→
  merge 汇总（fan-in）。多个 worker 同时跑，一次对话完成多个任务。
- 先收集信息再规划：行程 worker 内部两阶段（要素提取→生成），已具备

单意图路径完全不变（subtasks 为空走原条件边），保证不破坏已验收功能。
"""
import operator
from typing import TypedDict, Annotated

from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.types import Send
from langchain_core.messages import AnyMessage

from xiao_wen import intent
from xiao_wen.intent import SubTask
from xiao_wen.plugin_registry import discover, load_agent

# ---- 1. 子 Agent 清单（注册表自动发现：内置六 + 外部扩展）与懒加载 worker ----
_WORKER_NAMES = [m["INTENT"] for m in discover()]

def _worker(intent_name: str):
    """懒加载 worker：派发到该意图时才加载子 Agent 模块（与 system 同一注册表，调度增强不动子 Agent）"""
    def node(state):
        return load_agent(intent_name).run(state)
    return node

# ---- 2. State（增加调度优化字段） ----
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    recent: str
    intent: str
    reason: str
    answer: str
    subtasks: list[SubTask]  # 多意图拆分（SubTask 对象，不下沉 dict）
    current_task: SubTask    # Send 分支内当前子任务
    collected: Annotated[list[dict], operator.add]  # 并行结果收集（归约器拼接）

# ---- 3. 意图识别：多意图拆分（单一来源 xiao_wen.intent，C3） ----

def classify_intent(state):
    r = intent.classify(state["recent"], state["user_input"])
    return {"intent": r.intent, "reason": r.reason, "subtasks": r.subtasks}

# ---- 4. 并行执行：dispatcher（Send fan-out）+ 包装节点 + merge（fan-in） ----
def make_parallel(worker):
    """把原 worker 包成并行节点：读 Send 分支的 current_task，输出 collected（不覆盖 answer）"""
    def node(state):
        sub = state["current_task"]
        out = worker({**state, "user_input": sub.text})
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

# ---- 5. 组装图 ----
graph = StateGraph(State)
graph.add_node(classify_intent)
for name in _WORKER_NAMES:
    graph.add_node(name, _worker(name))
for name in _WORKER_NAMES:
    graph.add_node(f"p_{name}", make_parallel(_worker(name)))
graph.add_node(merge)

graph.add_edge(START, "classify_intent")
# 主路由：多意图 → Send fan-out 并行；单意图 → 原条件边（路径映射只含字符串分支）
graph.add_conditional_edges(
    "classify_intent",
    dispatch,
    {name: name for name in _WORKER_NAMES},
)
# 并行组：p_* → merge（fan-in）
for name in _WORKER_NAMES:
    graph.add_edge(f"p_{name}", "merge")
graph.add_edge("merge", END)
for name in _WORKER_NAMES:
    graph.add_edge(name, END)

app = graph.compile()

# ---- 6. 演示：单意图回归 + 多意图并行 ----
if __name__ == "__main__":
    from xiao_wen.session import chat
    demo = [
        # ① 单意图回归（subtasks 为空 → 原路由，不破坏）
        "10月8日去北京开会4天",
        # ② 多意图并行：知识问答 + 联网查询
        "帮我查下出差住宿标准是什么，顺便看看北京今天天气怎么样",
        # ③ 多意图并行：历史查询 + 联网查询
        "我上次的行程是什么，还有上海明天天气怎么样",
        # ④ 边界单意图
        "这个暑假去哪里玩",
    ]
    for t in demo:
        print("=" * 60)
        print(f"用户：{t}")
        r = chat(t, graph=app)
        print(f"意图：{r.intent}（{r.reason}）")
        # 拆分/并行信息体现在合并回答开头（“⚡ 同时为你处理了 N 个请求”）
        print(r.answer)
