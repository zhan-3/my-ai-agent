"""第六课：记忆 —— 偏好落库 + 历史查询 + 行程规划读取偏好（系统 v2）
跑法：python homework/0006_memory.py
依赖：项目根目录 .env；homework/memory_store.py（JSON 文件记忆）

本次升级的三个 worker：
- preference（做实）：提取偏好 → 写入记忆
- history（做实）：从记忆读历史行程 → 返回给用户
- itinerary（升级）：生成前读取用户历史偏好 → 排出的行程符合偏好；行程生成后写回记忆
其余 worker 仍为桩（后续课程做实）。
"""
from typing import TypedDict, Annotated, Literal
import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END, add_messages
from langchain_core.messages import AnyMessage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, SecretStr

from memory_store import (add_or_update_preference, add_itinerary,
                          get_preferences, get_itineraries)

load_dotenv()

# ---- 1. LLM（同一套可用配置） ----
llm = ChatOpenAI(
    model=os.environ["DEEPSEEK_MODEL"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
    api_key=SecretStr(os.environ["DEEPSEEK_API_KEY"]),
    temperature=0,
    extra_body={"thinking": {"type": "disabled"}},
)

# ---- 2. Schema ----
class PreferenceRecord(BaseModel):
    """用户偏好记录"""
    category: Literal["住宿", "餐饮", "交通", "预算", "其他"]
    content: str = Field(description="偏好内容的一句话")

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

# ---- 3. 各阶段提示词 ----
pref_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是企业差旅助手的偏好提取器，输出严格 JSON。
从用户原话提取偏好，键名必须严格为英文：category（必须严格是五个词之一：住宿、餐饮、交通、预算、其他）、content（偏好内容一句话）。
示例：{{"category": "住宿", "content": "喜欢住全季酒店"}}"""),
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

# ---- 4. State ----
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    intent: str
    reason: str
    answer: str

# ---- 5. 主管（真 LLM） ----
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
示例：{{"intent": "行程规划", "reason": "用户要求安排出差行程"}}"""),
    ("human", "{input}"),
])
class Intent(BaseModel):
    intent: Literal["行程规划", "偏好记录", "历史查询", "知识问答", "联网查询", "其他"]
    reason: str

intent_model = intent_prompt | llm.with_structured_output(Intent, method="json_mode")

def classify_intent(state):
    r = intent_model.invoke({"input": state["user_input"]})
    assert isinstance(r, Intent)
    return {"intent": r.intent, "reason": r.reason}

# ---- 6. 做实/升级的工人 ----
def preference(state):
    r = pref_model.invoke({"input": state["user_input"]})
    assert isinstance(r, PreferenceRecord)  # json_mode 结构化输出返回模型实例
    rec = add_or_update_preference(r.category, r.content)  # 0006 阶段无更新语气，默认新增
    return {"answer": f"✅ 已记录偏好：{rec['category']}｜{rec['content']}（{rec['ts']}）"}

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
    assert isinstance(req, TripRequest)
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
    add_itinerary(req.model_dump(), plan.summary)  # 行程写回记忆 → 历史查询可读
    return {"answer": format_plan(plan)}

# ---- 7. 未实做的工人（桩） ----
def knowledge_stub(state):
    return {"answer": f"【知识问答·桩】我会去查差旅政策库：{state['user_input']}（后续课程做实）"}

def web_stub(state):
    return {"answer": f"【联网查询·桩】我会去查实时信息：{state['user_input']}（后续课程做实）"}

def other_stub(state):
    return {"answer": f"【其他·桩】抱歉，暂时无法处理：{state['user_input']}（后续课程做实）"}

# ---- 8. 组装图 ----
graph = StateGraph(State)
graph.add_node(classify_intent)
for name, fn in [("itinerary", itinerary), ("preference", preference), ("history", history),
                 ("knowledge", knowledge_stub), ("web", web_stub), ("other", other_stub)]:
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

# ---- 9. 演示：记忆闭环 ----
if __name__ == "__main__":
    demo = [
        "我不吃辣",
        "10月8日从广州去北京开会4天",
        "我上次的行程是什么",
        "帮我安排出差行程",
    ]
    for t in demo:
        print("=" * 50)
        print(f"用户：{t}")
        r = app.invoke({"messages": [], "user_input": t})
        print(f"意图：{r['intent']}（{r['reason']}）")
        print(r["answer"])
