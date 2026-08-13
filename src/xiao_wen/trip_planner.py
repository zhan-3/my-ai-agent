"""行程规划管线（ADR-0003）：要素提取 → 常驻城市补全 → 缺项检查 → 生成 → 写回 → 格式化

单一接口 plan(user_input) -> PlanResult | NeedsInfo（判别式返回，缺项清单可测）。
编排顺序是产品行为，勿改：常驻城市补全**先于**缺项检查（“用户没说出发城市但记忆里有”
不算缺项）；缺项短路不调生成；写回发生在生成成功后。
"""

# ruff: noqa: E501 —— 本模块是 prompt 密集模块：发给 LLM 的提示词内容行
# （要素示例、约束、reasons 说明）天然超行宽，拆分会改变提示词（换行=内容）。
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from xiao_wen import llm
from xiao_wen.memory import add_itinerary, get_home_city, get_preferences

# 相对日期解析：给提取器注入「今天」（含周几），让「下周/明天」能推算成具体日期
_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _today_cn() -> str:
    d = date.today()
    return f"{d.isoformat()}（{_WEEKDAYS[d.weekday()]}）"

# ---- Schema（与领域契约一致） ----


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


@dataclass
class PlanResult:
    plan: ItineraryPlan  # 生成的行程（已写回长期记忆）


@dataclass
class NeedsInfo:
    missing: list[str]  # 缺失要素清单（基础项 E：缺项提示）


# ---- 两阶段提示词（与验收契约一致） ----

extract_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是企业差旅助手的要素提取器，输出严格 JSON。
键名必须严格为英文：from_city、to_city、start_date（YYYY-MM-DD）、duration_days（数字）、
hotel_pref（没有填"无"）、budget_pref（经济/中等/舒适，没有填"中等"）。
相对时间（如「下周」「明天」「下周一」「后天」）必须按「今天」推算成具体 YYYY-MM-DD，不要填"待定"；完全没提日期才填"待定"。
示例：{{"from_city": "北京", "to_city": "杭州", "start_date": "2026-08-20", "duration_days": 3, "hotel_pref": "无", "budget_pref": "中等"}}""",
        ),
        ("human", "今天是 {today}。\n用户输入：{input}"),
    ]
)

plan_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是资深差旅规划师，输出严格 JSON。基于差旅要素生成企业差旅行程。
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

输出键名严格为英文：days（数组，每项键名 date/transport/hotel/activities/notes）、summary、reasons（字符串数组）。""",
        ),
        ("human", "差旅要素：{trip_json}\n用户历史偏好：{prefs}\n用户原话：{user_input}"),
    ]
)


# ---- 链（走 LLM 单一接缝，懒构建） ----


@lru_cache
def _extract_model():
    return extract_prompt | llm.get_llm().with_structured_output(TripRequest, method="json_mode")


@lru_cache
def _plan_model():
    return plan_prompt | llm.get_llm().with_structured_output(ItineraryPlan, method="json_mode")


# ---- 编排 ----


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


def plan(user_input: str, *, session_id: str = "default") -> PlanResult | NeedsInfo:
    """编排：提取 → 常驻城市补全 → 缺项检查（短路）→ 生成 → 写回长期记忆

    顺序是产品行为（ADR-0003），勿改。
    """
    req = _extract_model().invoke({"input": user_input, "today": _today_cn()})
    assert isinstance(req, TripRequest)
    # 常驻城市补全：先于缺项检查（"用户没说出发城市但记忆里有"不算缺项）
    hc = get_home_city(session_id=session_id)
    if (not req.from_city or req.from_city in ("待定", "未知")) and hc:
        req.from_city = hc
    miss = _missing(req)
    if miss:
        return NeedsInfo(missing=miss)
    prefs = get_preferences(session_id=session_id)
    prefs_text = "；".join(f"{p['category']}:{p['content']}" for p in prefs) or "无"
    plan = _plan_model().invoke(
        {
            "trip_json": req.model_dump_json(),
            "prefs": prefs_text,
            "user_input": user_input,
        }
    )
    assert isinstance(plan, ItineraryPlan)
    add_itinerary(req.model_dump(), plan.summary, session_id=session_id)
    return PlanResult(plan=plan)


# ---- 展示（可读性格式化，测试锁定） ----


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


def needs_info_text(needs: NeedsInfo) -> str:
    """缺项提示文案（基础项 E）"""
    return (
        "⚠️ 还缺一些信息才能帮你安排行程，请补充：\n· "
        + "\n· ".join(needs.missing)
        + "\n（例如：「10月8日从广州去北京开会4天」）"
    )
