"""第十课：组装完整系统 v3 —— 六个 worker 全部做实（多 Agent 系统总装）
跑法：python homework/0010_system.py
依赖：.env（DEEPSEEK_* + DASHSCOPE_API_KEY）；homework/memory_store.py（记忆，含短期+长期两层）
      0008_rag_vector.py（向量知识问答）、0009_web.py（联网查询图）

架构（和 0006 系统 v2 相同骨架，两处桩升级为真实现）：
- 意图识别：LLM 主管（六分类，json_mode）+ 注入最近对话（短期记忆）
- 行程规划：两阶段管线（要素提取→行程生成）+ 偏好注入 + 常驻城市补全 + 行程写回记忆
- 偏好记录 / 历史查询：长期记忆（JSON），偏好支持追加/覆盖（is_update）
- 知识问答：向量检索（dashscope text-embedding-v3 + chromadb，来自 0008）
- 联网查询：ToolNode ReAct 循环（天气/汇率/空气质量，来自 0009）+ 上文上下文注入（指代消解）
- 其他：兜底（产品边界外的请求）

记忆分层（对应 LangChain 官方 memory 概念）：
- 短期记忆：最近 N 轮对话（memory_store.messages），每轮 invoke 前注入 —— 官方对应 checkpointer+thread
- 长期记忆：偏好（含常驻城市，追加/覆盖）、历史行程、常用目的地 —— 官方对应 store
- hot path 权衡：注入克制（截断最近 6 轮），避免全量历史塞上下文（变慢、变贵、干扰）
"""
import importlib.util
from typing import TypedDict, Annotated, Literal
import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END, add_messages
from langchain_core.messages import AnyMessage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, SecretStr

from memory_store import (add_or_update_preference, add_message, add_itinerary,
                          get_preferences, get_itineraries, get_home_city,
                          format_recent_messages)

load_dotenv()

# ---- 1. LLM（同一套可用配置） ----
llm = ChatOpenAI(
    model=os.environ["DEEPSEEK_MODEL"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
    api_key=SecretStr(os.environ["DEEPSEEK_API_KEY"]),
    temperature=0,
    extra_body={"thinking": {"type": "disabled"}},
)

# ---- 2. Schema（与 0006 一致） ----
class PreferenceRecord(BaseModel):
    """用户偏好记录"""
    category: Literal["住宿", "餐饮", "交通", "预算", "常驻城市", "其他"]
    content: str = Field(description="偏好内容的一句话")
    is_update: bool = Field(default=False, description="True=覆盖同类别旧条目；False=新增")

class TripRequest(BaseModel):
    from_city: str
    to_city: str
    start_date: str
    duration_days: int
    hotel_pref: str = Field(description="没有则填'无'")
    budget_pref: str = Field(description="没有则填'中等'")

class DayPlan(BaseModel):
    date: str
    transport: str
    hotel: str
    activities: list[str]
    notes: str

class ItineraryPlan(BaseModel):
    days: list[DayPlan]
    summary: str
    reasons: list[str] = Field(description="安排理由列表，每项一句（政策约束/偏好/交通合理性等）")

# ---- 3. 各阶段提示词（与 0006 一致） ----
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
pref_model = pref_prompt | llm.with_structured_output(PreferenceRecord, method="json_mode")

extract_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是企业差旅助手的要素提取器，输出严格 JSON。
键名必须严格为英文：from_city、to_city、start_date（YYYY-MM-DD，没给日期填"待定"）、
duration_days（数字）、hotel_pref（没有填"无"）、budget_pref（经济/中等/舒适，没有填"中等"）。
示例：{{"from_city": "北京", "to_city": "杭州", "start_date": "2026-08-20", "duration_days": 3, "hotel_pref": "无", "budget_pref": "中等"}}"""),
    ("human", "{input}"),
])
extract_model = extract_prompt | llm.with_structured_output(TripRequest, method="json_mode")

plan_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是资深差旅规划师，输出严格 JSON。基于差旅要素生成企业差旅行程。
约束：
- 天数与要素一致；每天包含 transport、hotel、activities、notes 四个字段
- 交通方式符合城市间距离；活动含公务安排和用餐建议
- 住宿必须符合用户的【历史偏好】，偏好没提到再按预算安排；酒店给品牌/档位即可
- reasons：安排理由列表，每项一句，涵盖政策约束、用户偏好、交通合理性，例如："住宿按差旅政策一线城市不超过500元/晚"、"考虑你不吃辣的偏好安排清淡餐饮"
- summary 是给用户看的中文总结（不含 JSON）

字段形状必须严格如下（都是简单值，禁止嵌套对象！）：
- transport：一句话字符串，如 "高铁 G31 次 08:00 北京南→12:30 杭州东"
- hotel：字符串，如 "全季酒店（杭州西湖店）"；最后一天返程写 "无（当晚返程）"
- activities：字符串数组，每项一句，如 "14:00-17:00 公务：拜访客户公司"、"18:30-20:00 用餐：与客户晚餐"
- notes：字符串，一两句备注

输出键名严格为英文：days（数组，每项键名 date/transport/hotel/activities/notes）、summary、reasons（字符串数组）。"""),
    ("human", "差旅要素：{trip_json}\n用户历史偏好：{prefs}\n用户原话：{user_input}"),
])
plan_model = plan_prompt | llm.with_structured_output(ItineraryPlan, method="json_mode")

# ---- 4. 导入外部 worker 模块（0008 向量知识问答、0009 联网查询图）----
def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

rag = _load("rag_v3", "homework/0008_rag_vector.py")   # rag.knowledge_qa(query) -> str
web = _load("web_v3", "homework/0009_web.py")          # web.app 图 + web.SYSTEM

# ---- 5. State ----
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    recent: str  # 短期记忆：最近对话（每轮 invoke 前注入）
    intent: str
    reason: str
    answer: str

# ---- 6. 主管（真 LLM，与 0006 一致） ----
intent_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是企业差旅助手的意图分类器，输出严格 JSON。规则：
- 用户请助理安排行程、出差计划 → 行程规划
- 用户陈述个人偏好（住宿/餐饮/出行风格）→ 偏好记录
- 用户问历史对话/历史行程 → 历史查询
- 用户问差旅政策、报销、预订流程 → 知识问答
- 用户要查实时信息（天气、航班、交通）→ 联网查询
- 以上都不像 → 其他
一句话里有多个特征时，选主导意图。

边界：本助手只服务企业差旅。个人休闲/旅游规划、非差旅问题一律归「其他」。

输出必须是 JSON 对象，键名必须严格为英文 "intent" 和 "reason"：
- "intent" 严格是六词之一：行程规划、偏好记录、历史查询、知识问答、联网查询、其他
- "reason" 一句话理由
参考最近对话理解省略/指代（如「那上海呢」指上一轮提到的城市）
示例：{{"intent": "行程规划", "reason": "用户要求安排出差行程"}}。"""),
    ("human", "最近对话：\n{recent}\n\n当前用户输入：{input}"),
])
class Intent(BaseModel):
    intent: Literal["行程规划", "偏好记录", "历史查询", "知识问答", "联网查询", "其他"]
    reason: str

intent_model = intent_prompt | llm.with_structured_output(Intent, method="json_mode")

def classify_intent(state):
    r = intent_model.invoke({"recent": state["recent"], "input": state["user_input"]})
    assert isinstance(r, Intent)
    return {"intent": r.intent, "reason": r.reason}

# ---- 7. 六个 worker（全部做实） ----
def preference(state):
    r = pref_model.invoke({"input": state["user_input"]})
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

def format_plan(plan: ItineraryPlan) -> str:
    lines = [f"📋 {plan.summary}", ""]
    if plan.reasons:
        lines.append("💡 安排理由：")
        for r in plan.reasons:
            lines.append(f"  · {r}")
        lines.append("")
    for d in plan.days:
        lines.append(f"【{d.date}】")
        lines.append(f"  交通：{d.transport}")
        lines.append(f"  住宿：{d.hotel}")
        for a in d.activities:
            lines.append(f"  活动：{a}")
        if d.notes:
            lines.append(f"  备注：{d.notes}")
        lines.append("")
    return "\n".join(lines)

def _missing(req: TripRequest) -> list[str]:
    """检查必填要素缺失，返回缺失清单（基础项 E：缺失信息提示）"""
    miss = []
    if not req.to_city or req.to_city in ("待定", "未知"):
        miss.append("目的城市")
    if not req.from_city or req.from_city in ("待定", "未知"):
        miss.append("出发城市")
    if req.start_date in ("待定", ""):
        miss.append("出发日期")
    if not req.duration_days or req.duration_days <= 0:
        miss.append("出差天数")
    return miss

def itinerary(state):
    req = extract_model.invoke({"input": state["user_input"]})
    assert isinstance(req, TripRequest)  # with_structured_output(json_mode) 返回模型实例
    # 常驻城市补全：用户没说出发城市时用长期记忆（「下次直接说去哪别再傻问」）
    hc = get_home_city()
    if (not req.from_city or req.from_city in ("待定", "未知")) and hc:
        req.from_city = hc
    # 缺失信息检查：要素不全不硬生成，先问用户补（基础项 E）
    miss = _missing(req)
    if miss:
        return {"answer": "⚠️ 还缺一些信息才能帮你安排行程，请补充：\n· "
                + "\n· ".join(miss)
                + "\n（例如：「10月8日从广州去北京开会4天」）"}
    prefs = get_preferences()
    prefs_text = "；".join(f"{p['category']}:{p['content']}" for p in prefs) or "无"
    plan = plan_model.invoke({
        "trip_json": req.model_dump_json(),
        "prefs": prefs_text,
        "user_input": state["user_input"],
    })
    assert isinstance(plan, ItineraryPlan)
    add_itinerary(req.model_dump(), plan.summary)
    return {"answer": format_plan(plan)}

def knowledge(state):
    """真实现：向量检索知识问答（0008：embedding + chromadb）"""
    return {"answer": rag.knowledge_qa(state["user_input"])}

def web_query(question: str, ctx: str = "无") -> str:
    """调 0009 的 ToolNode 图（ReAct 循环），返回最终回答文本。ctx=短期记忆上下文，支持指代消解"""
    msgs = [web.SYSTEM]
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

# ---- 9. 演示：三类案例端到端（作业演示要求） ----
if __name__ == "__main__":
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
        # 短期记忆：每轮 invoke 前注入最近对话（hot path 检索，克制截断）
        recent = format_recent_messages(6)
        r = app.invoke({"messages": [("human", t)], "user_input": t, "recent": recent})
        # 写入短期记忆（hot path 写入）
        add_message("user", t)
        print(f"意图：{r['intent']}（{r['reason']}）")
        print(r["answer"])
        add_message("assistant", r["answer"])
