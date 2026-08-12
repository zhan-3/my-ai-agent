"""第四课：调度器骨架 —— 意图识别 + 条件边 → 「主管-工人」架构
跑法：python homework/0004_scheduler.py
依赖：项目根目录 .env；homework/0003_intent.py 同款 LLM 配置（thinking 关闭 + json_mode）

架构：
  START → classify_intent(LLM) → 条件边 → 按 intent 分流到 6 个工人桩节点 → END
  （桩 = stub：先返回占位结果，验证全链路；下一课逐个做实）
"""
from typing import TypedDict, Annotated, Literal
import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END, add_messages
from langchain_core.messages import AnyMessage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, SecretStr

load_dotenv()

# ---- 1. LLM（与 0003 相同的可用配置） ----
llm = ChatOpenAI(
    model=os.environ["DEEPSEEK_MODEL"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
    api_key=SecretStr(os.environ["DEEPSEEK_API_KEY"]),
    temperature=0,
    extra_body={"thinking": {"type": "disabled"}},
)

class Intent(BaseModel):
    intent: Literal["行程规划", "偏好记录", "历史查询", "知识问答", "联网查询", "其他"]
    reason: str = Field(description="一句话理由")

prompt = ChatPromptTemplate.from_messages([
    ("system", """你是企业差旅助手的意图分类器，输出严格 JSON。规则：
- 用户请助理安排行程、出差计划 → 行程规划
- 用户陈述个人偏好（住宿/餐饮/出行风格）→ 偏好记录
- 用户问历史对话/历史行程 → 历史查询
- 用户问差旅政策、报销、预订流程 → 知识问答
- 用户要查实时信息（天气、航班、交通）→ 联网查询
- 以上都不像 → 其他
一句话里有多个特征时，选主导意图。

边界：本助手只服务企业差旅。个人休闲/旅游规划（如暑假去哪玩、周末去哪玩）、非差旅问题一律归「其他」。

输出必须是 JSON 对象，键名必须严格为英文 "intent" 和 "reason"：
- "intent" 的值必须严格是六个词之一：行程规划、偏好记录、历史查询、知识问答、联网查询、其他
- "reason" 的值是一句话理由（字符串）
示例：{{"intent": "行程规划", "reason": "用户要求安排出差行程"}}"""),
    ("human", "{input}"),
])
intent_model = prompt | llm.with_structured_output(Intent, method="json_mode")

# ---- 2. State ----
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    intent: str          # classify 写，路由读
    reason: str
    answer: str          # 工人写回给用户的最终答复

# ---- 3. 主管节点（真 LLM） ----
def classify_intent(state):
    result = intent_model.invoke({"input": state["user_input"]})
    assert isinstance(result, Intent)
    return {"intent": result.intent, "reason": result.reason}

# ---- 4. 六个工人桩节点（纯代码，先占位；下一课逐个做实） ----
def itinerary_stub(state):
    return {"answer": f"【行程规划·桩】我会为用户安排行程：{state['user_input']}（下节课做实）"}

def preference_stub(state):
    return {"answer": f"【偏好记录·桩】已记录用户偏好：{state['user_input']}（下节课做实）"}

def history_stub(state):
    return {"answer": f"【历史查询·桩】我会去查历史行程：{state['user_input']}（下节课做实）"}

def knowledge_stub(state):
    return {"answer": f"【知识问答·桩】我会去查差旅政策库：{state['user_input']}（下节课做实）"}

def web_stub(state):
    return {"answer": f"【联网查询·桩】我会去查实时信息：{state['user_input']}（下节课做实）"}

def other_stub(state):
    return {"answer": f"【其他·桩】抱歉，暂时无法处理：{state['user_input']}（下节课做实）"}

# ---- 5. 组装图：调度骨架 ----
graph = StateGraph(State)
graph.add_node(classify_intent)
for name, fn in [("itinerary", itinerary_stub), ("preference", preference_stub),
                 ("history", history_stub), ("knowledge", knowledge_stub),
                 ("web", web_stub), ("other", other_stub)]:
    graph.add_node(name, fn)

graph.add_edge(START, "classify_intent")
graph.add_conditional_edges(
    "classify_intent",                       # 主管：读 state["intent"] 决定交给谁
    lambda s: s["intent"],
    {
        "行程规划": "itinerary",
        "偏好记录": "preference",
        "历史查询": "history",
        "知识问答": "knowledge",
        "联网查询": "web",
        "其他": "other",
    },
)
for name in ["itinerary", "preference", "history", "knowledge", "web", "other"]:
    graph.add_edge(name, END)

app = graph.compile()

# ---- 6. 测试：六类意图各来一句 ----
tests = [
    "我下周三去上海出差两天，帮我安排行程",
    "我喜欢住全季酒店",
    "我上次的北京行程是什么",
    "公司差旅报销标准是多少",
    "明天北京到上海的航班有吗",
    "今天天气不错",
    "帮我看看出差的事",
    "这个暑假去哪里玩",
]
for t in tests:
    r = app.invoke({"messages": [], "user_input": t})
    print(f"{t!r}\n  → {r['intent']}（{r['reason']}）\n  → {r['answer']}")
