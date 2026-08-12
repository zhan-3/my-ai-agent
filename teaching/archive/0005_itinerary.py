"""第五课：行程规划 worker 做实 —— 基础项 A 的核心
跑法：python homework/0005_itinerary.py
依赖：项目根目录 .env；DeepSeek v4 可用配置（thinking 关闭 + json_mode）

设计：worker 内部是两阶段管线（对应作业里的「要素提取」+「行程生成」）：
  用户原话 → ① 要素提取(LLM)：TripRequest{出发地/目的地/日期/天数/偏好}
           → ② 行程生成(LLM)：ItineraryPlan{逐日安排 + 总结}
           → 用户可读文本
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

# ---- 1. LLM（与 0003/0004 相同的可用配置） ----
llm = ChatOpenAI(
    model=os.environ["DEEPSEEK_MODEL"],
    base_url=os.environ["DEEPSEEK_BASE_URL"],
    api_key=SecretStr(os.environ["DEEPSEEK_API_KEY"]),
    temperature=0,
    extra_body={"thinking": {"type": "disabled"}},
)

# ---- 2. 两阶段 schema ----
class TripRequest(BaseModel):
    """从用户话里提取的差旅要素"""
    from_city: str = Field(description="出发城市")
    to_city: str = Field(description="目的城市")
    start_date: str = Field(description="出发日期（YYYY-MM-DD）")
    duration_days: int = Field(description="出差天数")
    hotel_pref: str = Field(description="住宿偏好，没有则填'无'")
    budget_pref: str = Field(description="预算偏好（经济/中等/舒适），没有则填'中等'")

class DayPlan(BaseModel):
    date: str = Field(description="日期（YYYY-MM-DD）")
    transport: str = Field(description="当天交通安排")
    hotel: str = Field(description="当晚住宿")
    activities: list[str] = Field(description="当天活动（含公务和用餐）")
    notes: str = Field(description="备注")

class ItineraryPlan(BaseModel):
    days: list[DayPlan]
    summary: str = Field(description="行程总结")
    reasons: list[str] = Field(description="安排理由列表，每项一句（政策约束/偏好/交通合理性等）")

# ---- 3. 两阶段提示词（键名写死 + JSON 花括号转义） ----
extract_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是企业差旅助手的要素提取器，输出严格 JSON。
从用户原话里提取差旅要素，键名必须严格为英文：
from_city（出发城市）、to_city（目的城市）、start_date（出发日期，格式 YYYY-MM-DD，没给日期则填"待定"）、
duration_days（出差天数，数字）、hotel_pref（住宿偏好，没有填"无"）、budget_pref（预算偏好，经济/中等/舒适，没有填"中等"）。
示例：{{"from_city": "北京", "to_city": "杭州", "start_date": "2026-08-20", "duration_days": 3, "hotel_pref": "连锁酒店", "budget_pref": "中等"}}"""),
    ("human", "{input}"),
])
extract_model = extract_prompt | llm.with_structured_output(TripRequest, method="json_mode")

plan_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是资深差旅规划师，输出严格 JSON。基于用户给的差旅要素，生成一份合理的企业差旅行程。

约束：
- 天数与要素一致；每天必须包含 transport（交通）、hotel（当晚住宿）、activities（活动列表）、notes（备注）
- 考虑城市间距离合理选择交通方式（高铁/飞机）；活动含公务安排和用餐建议
- 住宿符合预算偏好；酒店给出品牌/档位即可，不用编造真实预订号
- reasons：安排理由列表，每项一句，涵盖政策约束、用户偏好、交通合理性，例如："住宿按差旅政策一线城市不超过500元/晚"、"考虑你不吃辣的偏好安排清淡餐饮"
- summary 是给用户看的一段中文总结（不含 JSON）

输出键名必须严格为英文：days（数组，每项键名 date/transport/hotel/activities/notes）、summary、reasons（字符串数组）。"""),
    ("human", "差旅要素：{trip_json}\n用户原话：{user_input}"),
])
plan_model = plan_prompt | llm.with_structured_output(ItineraryPlan, method="json_mode")

# ---- 4. worker 节点：两阶段管线 ----
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
    # ① 要素提取
    req = extract_model.invoke({"input": state["user_input"]})
    assert isinstance(req, TripRequest)  # json_mode 结构化输出返回模型实例
    # ①.5 缺失信息检查：要素不全不硬生成，先问用户补
    miss = _missing(req)
    if miss:
        return {"answer": "⚠️ 还缺一些信息才能帮你安排行程，请补充：\n· "
                + "\n· ".join(miss)
                + "\n（例如：「10月8日从广州去北京开会4天」）"}
    # ② 行程生成（把提取结果作为上下文交给生成阶段）
    plan = plan_model.invoke({
        "trip_json": req.model_dump_json(),
        "user_input": state["user_input"],
    })
    assert isinstance(plan, ItineraryPlan)
    return {"answer": format_plan(plan)}

# ---- 5. 组装：本次只测 worker 本身 ----
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    answer: str

graph = StateGraph(State)
graph.add_node(itinerary)
graph.add_edge(START, "itinerary")
graph.add_edge("itinerary", END)
app = graph.compile()

if __name__ == "__main__":
    tests = [
        "8月20日从北京去杭州出差三天，预算中等，喜欢住连锁酒店",
        "9月1日从上海到深圳开两天会，住舒适一点",
        "我下周出差"
    ]
    for t in tests:
        print("=" * 50)
        print(f"用户：{t}")
        r = app.invoke({"messages": [], "user_input": t})
        print(r["answer"])
