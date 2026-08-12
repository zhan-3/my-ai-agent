"""调度优化模块：同优先级任务并行执行（Send API fan-out/fan-in，加分项 B）
跑法：uv run python -m xiao_wen.scheduler
依赖：xiao_wen.system（复用六个 worker 节点函数）

设计（对比「固定顺序串行」）：
- 动态路由：按意图选 worker（条件边）
- ★并行执行：一句话含多个独立请求 → 意图识别拆分子任务（subtasks）→
  dispatcher 用 Send 把每个子任务并行派发给对应 worker（fan-out）→
  merge 汇总（fan-in）。多个 worker 同时跑，一次对话完成多个任务。
- 先收集信息再规划：行程 worker 内部两阶段（要素提取→生成），已具备

单意图路径完全不变（subtasks 为空走原条件边），保证不破坏已验收功能。
"""
import operator
from typing import TypedDict, Annotated, Literal

from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.types import Send
from langchain_core.messages import AnyMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from xiao_wen.memory import add_message, format_recent_messages

# ---- 1. 复用 xiao_wen.system 的六个 worker 节点函数（模块化：调度增强不动 worker） ----
from xiao_wen import system as base

WORKERS = {"行程规划": base.itinerary, "偏好记录": base.preference, "历史查询": base.history,
           "知识问答": base.knowledge, "联网查询": base.web_node, "其他": base.other}

# ---- 2. State（增加调度优化字段） ----
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    recent: str
    intent: str
    reason: str
    answer: str
    subtasks: list[dict]          # 多意图拆分：[{intent, text}, ...]
    current_task: dict            # Send 分支内当前子任务
    collected: Annotated[list[dict], operator.add]  # 并行结果收集（归约器拼接）

# ---- 3. 意图识别：支持多意图拆分 ----
intent_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是企业差旅助手的意图分类器，输出严格 JSON。规则：
- 用户请助理安排行程、出差计划 → 行程规划
- 用户陈述个人偏好（住宿/餐饮/出行风格）→ 偏好记录
- 用户问历史对话/历史行程 → 历史查询
- 用户问差旅政策、报销、预订流程 → 知识问答
- 用户要查实时信息（天气、航班、交通）→ 联网查询
- 以上都不像 → 其他
边界：本助手只服务企业差旅。个人休闲/旅游规划、非差旅问题一律归「其他」。

【多意图拆分】一句话里包含多个独立请求时（用"顺便/还有/以及/和"连接），
把每个独立请求拆成一条 subtasks（各自带 intent 和原文）；单一请求时 subtasks 为空数组 []。

输出键名必须严格为英文：
- "intent"：主导意图（严格六词之一），多意图时取第一个
- "reason"：一句话理由
- "subtasks"：数组，每项键名严格为 intent（六词之一）和 text（该子请求原文）
示例（单）：{{"intent": "行程规划", "reason": "要求安排出差行程", "subtasks": []}}
示例（多）：{{"intent": "知识问答", "reason": "包含政策和天气两个请求",
  "subtasks": [{{"intent": "知识问答", "text": "出差住宿标准是什么"}},
               {{"intent": "联网查询", "text": "北京今天天气怎么样"}}]}}"""),
    ("human", "最近对话：\n{recent}\n\n当前用户输入：{input}"),
])

class SubTask(BaseModel):
    intent: Literal["行程规划", "偏好记录", "历史查询", "知识问答", "联网查询", "其他"]
    text: str

class Intent(BaseModel):
    intent: Literal["行程规划", "偏好记录", "历史查询", "知识问答", "联网查询", "其他"]
    reason: str
    subtasks: list[SubTask] = []

intent_model = intent_prompt | base.llm.with_structured_output(Intent, method="json_mode")

def classify_intent(state):
    r = intent_model.invoke({"recent": state["recent"], "input": state["user_input"]})
    assert isinstance(r, Intent)
    return {"intent": r.intent, "reason": r.reason,
            "subtasks": [s.model_dump() for s in r.subtasks]}

# ---- 4. 并行执行：dispatcher（Send fan-out）+ 包装节点 + merge（fan-in） ----
def make_parallel(worker):
    """把原 worker 包成并行节点：读 Send 分支的 current_task，输出 collected（不覆盖 answer）"""
    def node(state):
        sub = state["current_task"]
        out = worker({**state, "user_input": sub["text"]})
        return {"collected": [{"intent": sub["intent"], "text": sub["text"], "answer": out["answer"]}]}
    return node

def dispatch(state):
    """fan-out 条件边函数：多意图 → Send 列表（并行执行）；单意图 → 字符串路由"""
    subs = state.get("subtasks")
    if subs:
        return [Send(f"p_{s['intent']}", {"current_task": s}) for s in subs]
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
for name, fn in WORKERS.items():
    graph.add_node(name, fn)
for intent in WORKERS:
    graph.add_node(f"p_{intent}", make_parallel(WORKERS[intent]))
graph.add_node(merge)

graph.add_edge(START, "classify_intent")
# 主路由：多意图 → Send fan-out 并行；单意图 → 原条件边（路径映射只含字符串分支）
graph.add_conditional_edges(
    "classify_intent",
    dispatch,
    {name: name for name in WORKERS},
)
# 并行组：p_* → merge（fan-in）
for intent in WORKERS:
    graph.add_edge(f"p_{intent}", "merge")
graph.add_edge("merge", END)
for name in WORKERS:
    graph.add_edge(name, END)

app = graph.compile()

# ---- 6. 演示：单意图回归 + 多意图并行 ----
if __name__ == "__main__":
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
        recent = format_recent_messages(6)
        r = app.invoke({"messages": [("human", t)], "user_input": t, "recent": recent})
        add_message("user", t)
        print(f"意图：{r['intent']}（{r['reason']}）")
        subs = r.get("subtasks") or []
        if subs:
            print(f"拆分为 {len(subs)} 个子任务（并行执行）：")
            for s in subs:
                print(f"  · {s['intent']}｜{s['text']}")
        print(r["answer"])
        add_message("assistant", r["answer"])
