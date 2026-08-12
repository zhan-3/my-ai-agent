"""第三课动手任务：语义意图识别（作业基础项 B 的核心）——最终可用版
跑法：python homework/0003_intent.py
依赖：项目根目录 .env（DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL）

【为什么这样写】（2026-08-10 调试实证）
- 模型是 deepseek-v4-flash（中转站），默认开 thinking 模式：
  · thinking 下 response_format(json_schema) 不可用 → 400 "This response_format type is unavailable now"
  · thinking 下强制 tool_choice 不可用 → 400 "Thinking mode does not support this tool_choice"
- 对策：extra_body 关 thinking + method="json_mode"（v4-flash 支持 json_object）
- json_mode 只保证是 JSON，不保证键名正确 → 系统提示词里写死英文键名 "intent"/"reason"
- 提示词模板里出现花括号要转义成 {{ }}（否则被当作模板变量）
"""
from typing import TypedDict, Annotated, Literal
import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END, add_messages
from langchain_core.messages import AnyMessage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, SecretStr

load_dotenv()  # 从项目根目录的 .env 加载三个变量

# ---- 1. 接上中转站（OpenAI 兼容接口） ----
llm = ChatOpenAI(
    model=os.environ["DEEPSEEK_MODEL"],       # 中转站给的模型名
    base_url=os.environ["DEEPSEEK_BASE_URL"],  # 中转站地址，通常以 /v1 结尾
    api_key=SecretStr(os.environ["DEEPSEEK_API_KEY"]),  # 包成 SecretStr：过类型检查 + 防日志泄露
    temperature=0,                             # 分类任务：0 = 最稳定
    extra_body={"thinking": {"type": "disabled"}},  # 关 DeepSeek V4 思考模式（否则 json 输出不可用）
)

# ---- 2. 声明结构化输出 schema ----
class Intent(BaseModel):
    """用户这句话属于哪类任务"""
    intent: Literal["行程规划", "偏好记录", "历史查询", "知识问答", "联网查询", "其他"]
    reason: str = Field(description="一句话理由")

# ---- 2.5 系统提示词：给模型定规则（缺它第一句会被带偏） ----
prompt = ChatPromptTemplate.from_messages([
    ("system", """你是企业差旅助手的意图分类器，输出严格 JSON。规则：
- 用户请助理安排行程、出差计划 → 行程规划
- 用户陈述个人偏好（住宿/餐饮/出行风格）→ 偏好记录
- 用户问历史对话/历史行程 → 历史查询
- 用户问差旅政策、报销、预订流程 → 知识问答
- 用户要查实时信息（天气、航班、交通）→ 联网查询
- 以上都不像 → 其他
一句话里有多个特征时，选主导意图。

输出必须是 JSON 对象，键名必须严格为英文 "intent" 和 "reason"：
- "intent" 的值必须严格是六个词之一：行程规划、偏好记录、历史查询、知识问答、联网查询、其他
- "reason" 的值是一句话理由（字符串）
示例：{{"intent": "行程规划", "reason": "用户要求安排出差行程"}}"""),
    ("human", "{input}"),
])

# json_mode：v4-flash 支持 json_object 但不支持 json_schema/强制 tool_choice
intent_model = prompt | llm.with_structured_output(Intent, method="json_mode")

# ---- 3. 图：一个「有大脑的节点」 ----
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]  # 官方惯例名：messages
    user_input: str
    intent: str
    reason: str

def classify_intent(state):
    result = intent_model.invoke({"input": state["user_input"]})  # 调 LLM（带规则）
    assert isinstance(result, Intent)  # json_mode 结构化输出返回模型实例
    return {"intent": result.intent, "reason": result.reason}

graph = StateGraph(State)
graph.add_node(classify_intent)
graph.add_edge(START, "classify_intent")
graph.add_edge("classify_intent", END)
app = graph.compile()

# ---- 4. 三句测试 ----
tests = [
    "我下周从北京去杭州出差三天，喜欢住连锁酒店",
    "帮我查一下报销标准是多少",
    "我喜欢住汉庭",
]
for t in tests:
    r = app.invoke({"messages": [], "user_input": t})
    print(f"{t!r} → {r['intent']}（{r['reason']}）")
