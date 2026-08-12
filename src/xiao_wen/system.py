"""完整系统模块：多 Agent 主管总装（六个 Worker 全部做实）
跑法：uv run python -m xiao_wen.system
依赖：.env（DEEPSEEK_* + DASHSCOPE_API_KEY）；xiao_wen.memory（记忆，短期+长期两层）
      xiao_wen.rag（向量知识问答）、xiao_wen.web（联网查询图）

架构（主管-工人 Supervisor–Workers）：
- 意图识别：LLM 主管（六分类，json_mode）+ 注入最近对话（短期记忆）
- 行程规划：两阶段管线（要素提取→行程生成）+ 偏好注入 + 常驻城市补全 + 行程写回记忆
- 偏好记录 / 历史查询：长期记忆（JSON），偏好支持追加/覆盖（is_update）
- 知识问答：向量检索（dashscope text-embedding-v3 + chromadb，来自 xiao_wen.rag）
- 联网查询：ToolNode ReAct 循环（天气/汇率/空气质量，来自 xiao_wen.web）+ 上下文注入（指代消解）
- 其他：兜底（产品边界外的请求）

记忆分层（对应 LangChain 官方 memory 概念）：
- 短期记忆：最近 N 轮对话（memory.messages），每轮 invoke 前注入 —— 对应 checkpointer+thread
- 长期记忆：偏好（含常驻城市，追加/覆盖）、历史行程 —— 对应 store
- hot path 权衡：注入克制（截断最近 6 轮），避免全量历史塞上下文（变慢、变贵、干扰）
"""
from typing import Any, TypedDict, Annotated, Literal
from functools import lru_cache
from langgraph.graph import StateGraph, START, END, add_messages
from langchain_core.messages import AnyMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from xiao_wen import llm
from xiao_wen.memory import add_or_update_preference, get_itineraries
from xiao_wen.trip_planner import NeedsInfo, format_plan, plan as _trip_plan

# ---- 1. LLM：单一接缝（xiao_wen.llm，懒构造 + 熔断守卫；链在本模块懒构建） ----

# ---- 2. Schema（与 0006 一致） ----
class PreferenceRecord(BaseModel):
    """用户偏好记录"""
    category: Literal["住宿", "餐饮", "交通", "预算", "常驻城市", "其他"]
    content: str = Field(description="偏好内容的一句话")
    is_update: bool = Field(default=False, description="True=覆盖同类别旧条目；False=新增")

# ---- 3. 偏好提示词（行程规划两阶段提示词已随管线迁入 xiao_wen.trip_planner，ADR-0003） ----
pref_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是企业差旅助手的偏好提取器，输出严格 JSON。
从用户原话提取偏好，键名必须严格为英文：
- category：严格是六词之一：住宿、餐饮、交通、预算、常驻城市、其他
- content：偏好内容一句话
- is_update：布尔。用户表达「现在/改成/以后/不再/其实是」等更新语气时 true，否则 false。
  示例：「我喜欢住汉庭」→ false（新增）；「我现在常住上海」→ true（更新常驻城市）
输出示例：{{"category": "住宿", "content": "喜欢住全季酒店", "is_update": false}}，
更新示例：{{"category": "常驻城市", "content": "上海", "is_update": true}}。"""),
    ("human", "{input}"),
])
@lru_cache
def _pref_model():
    return pref_prompt | llm.get_llm().with_structured_output(PreferenceRecord, method="json_mode")

# ---- 4. 导入外部 worker 模块（xiao_wen.rag 向量知识问答、xiao_wen.web 联网查询图）----
from xiao_wen import rag   # rag.knowledge_qa(query) -> str
from xiao_wen import web   # web.app 图 + web.SYSTEM

# ---- 5. State ----
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    recent: str  # 短期记忆：最近对话（每轮 invoke 前注入）
    intent: str
    reason: str
    answer: str

# ---- 6. 主管：意图分类（单一来源 xiao_wen.intent，真 LLM） ----
from xiao_wen.intent import Intent, classify as _classify

def classify_intent(state):
    r = _classify(state["recent"], state["user_input"])
    return {"intent": r.intent, "reason": r.reason}

# ---- 7. 六个 worker（全部做实） ----
def preference(state):
    r = _pref_model().invoke({"input": state["user_input"]})
    assert isinstance(r, PreferenceRecord)
    # 追加/覆盖区分：is_update=True 时替换同类别旧条目（如「我现在常住上海」）
    rec = add_or_update_preference(r.category, r.content, r.is_update)
    act = "更新" if r.is_update else "新增"
    return {"answer": f"✅ 已{act}偏好：{rec['category']}｜{rec['content']}（{rec['ts']}）"}

def history(state):
    its = get_itineraries()
    if not its:
        return {"answer": "📭 暂无历史行程记录。"}
    lines = ["🗂️ 历史行程："]
    for it in reversed(its[-5:]):  # 最多显示最近 5 条
        lines.append(f"· {it.get('start_date', '?')} {it.get('from_city', '?')}→{it.get('to_city', '?')}，{it.get('duration_days', '?')}天：{it.get('summary', '')[:40]}")
    return {"answer": "\n".join(lines)}

def itinerary(state):
    """行程规划：两阶段管线收口于 xiao_wen.trip_planner.plan（ADR-0003）"""
    r = _trip_plan(state["user_input"])
    if isinstance(r, NeedsInfo):
        return {"answer": "⚠️ 还缺一些信息才能帮你安排行程，请补充：\n· "
                + "\n· ".join(r.missing)
                + "\n（例如：「10月8日从广州去北京开会4天」）"}
    return {"answer": format_plan(r.plan)}

def knowledge(state):
    """真实现：向量检索知识问答（embedding + chromadb）"""
    return {"answer": rag.knowledge_qa(state["user_input"])}

def web_query(question: str, ctx: str = "无") -> str:
    """调 xiao_wen.web 的 ToolNode 图（ReAct 循环），返回最终回答文本。ctx=短期记忆上下文，支持指代消解"""
    msgs: list[Any] = [web.SYSTEM]
    if ctx != "无":
        msgs.append(("system", f"以下是本次对话上文，新问题可能省略了主语（如「那上海呢」）：\n{ctx}"))
    msgs.append(("human", question))
    result = web.app.invoke({"messages": msgs})
    return result["messages"][-1].content

def web_node(state):
    """真实现：联网查询（0009：天气/汇率/空气质量）+ 短期记忆上下文"""
    return {"answer": web_query(state["user_input"], state.get("recent", "无"))}

def other(state):
    return {"answer": f"抱歉，这不在企业差旅助手的服务范围内（如个人休闲旅游、非差旅问题）。当前仅支持：行程规划、偏好、历史行程、差旅政策、实时信息。"}

# ---- 8. 组装图（与 0006 相同拓扑） ----
graph = StateGraph(State)
graph.add_node(classify_intent)
for name, fn in [("itinerary", itinerary), ("preference", preference), ("history", history),
                 ("knowledge", knowledge), ("web", web_node), ("other", other)]:
    graph.add_node(name, fn)

graph.add_edge(START, "classify_intent")
graph.add_conditional_edges(
    "classify_intent",
    lambda s: s["intent"],
    {"行程规划": "itinerary", "偏好记录": "preference", "历史查询": "history",
     "知识问答": "knowledge", "联网查询": "web", "其他": "other"},
)
for name in ["itinerary", "preference", "history", "knowledge", "web", "other"]:
    graph.add_edge(name, END)

app = graph.compile()

# ---- 9. 演示：三类案例端到端 ----
if __name__ == "__main__":
    from xiao_wen.session import chat
    demo = [
        # ① 偏好新增（长期记忆写入）
        "我不吃辣，住宿喜欢安静",
        # ② 常驻城市（长期记忆更新：覆盖同类别）
        "我现在常住上海",
        # ③ 行程规划：不说出发城市 → 用常驻城市上海（别再傻问）
        "10月8日去北京开会4天",
        # ④ 联网查询
        "北京今天天气怎么样？",
        # ⑤ 指代消解：靠短期记忆（最近对话）理解「那上海呢」= 问天气
        "那上海呢",
        # ⑥ 历史查询（读长期记忆）
        "我上次的行程是什么",
        # ⑦ 边界（应归「其他」）
        "这个暑假去哪里玩",
    ]
    for t in demo:
        print("=" * 56)
        print(f"用户：{t}")
        r = chat(t)
        print(f"意图：{r.intent}（{r.reason}）")
        print(r.answer)
