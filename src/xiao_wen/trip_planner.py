"""行程规划管线（ADR-0003）：要素提取 → 常驻城市补全 → 缺项检查 → 生成 → 写回 → 格式化

单一接口 plan(user_input) -> PlanResult | NeedsInfo（判别式返回，缺项清单可测）。
编排顺序是产品行为，勿改：常驻城市补全**先于**缺项检查（“用户没说出发城市但记忆里有”
不算缺项）；缺项短路不调生成；写回发生在生成成功后。
"""

# ruff: noqa: E501 —— 本模块是 prompt 密集模块：发给 LLM 的提示词内容行
# （要素示例、约束、reasons 说明）天然超行宽，拆分会改变提示词（换行=内容）。
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from xiao_wen import llm
from xiao_wen.memory import add_itinerary, get_home_city, get_preferences
from xiao_wen.ticket_link import build_ticket_url

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
    # int | str：提取 LLM 缺天数时可能输出「待定/无」（实测 pydantic 曾因此校验崩溃），
    # plan() 哨兵归一化成 0 后再走缺项检查
    duration_days: int | str = 0
    # int | str：人数同天数，LLM 可能输出「待定/无」，plan() 哨兵归一化成 1
    people_count: int | str = 1
    purpose: str = Field(default="", description="出行目的（开会/拜访客户/旅游等）；没提填空字符串")
    return_date: str = Field(default="", description="返程日期 YYYY-MM-DD；用户没给具体返程日期填空字符串")
    transport_pref: str = Field(default="无", description="交通偏好（高铁/飞机/无）；没提填'无'")
    hotel_pref: str = Field(description="没有则填'无'")
    budget_pref: str = Field(description="没有则填'中等'")
    date_is_vague: bool = Field(
        default=False,
        description="日期表达模糊（只说了下周/过几天等，无法确定到具体哪天）时为 true；给了具体日期或星期几时为 false",
    )


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
    request: TripRequest | None = None  # 提取的行程要素（供展示层附加目的地天气等）


@dataclass
class NeedsInfo:
    missing: list[str]  # 缺失要素清单（基础项 E：缺项提示）
    request: TripRequest | None = None


@dataclass
class ValidationFailure:
    """候选行程未通过运行时验证；失败结果不得写回长期记忆。"""

    issues: list[str]


# ---- 两阶段提示词（与验收契约一致） ----

extract_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是企业差旅助手的要素提取器，输出严格 JSON。
键名必须严格为英文：from_city、to_city、start_date（YYYY-MM-DD）、duration_days（数字；完全没提天数时填 0，不要填"待定"）、
people_count（数字；没提填 1）、purpose（开会/拜访客户/旅游等；没提填空字符串）、return_date（YYYY-MM-DD；用户给了具体返程日期才填，没给填空字符串）、
transport_pref（高铁/飞机/无；没提填"无"）、hotel_pref（没有填"无"）、budget_pref（经济/中等/舒适，没有填"中等"）、
date_is_vague（布尔：日期表达模糊如「下周」「过几天」时为 true；给了具体日期或星期几如「8月17日」「下周一」「明天」时为 false）。
from_city/to_city：只在原文明确提到城市时才填（如「从广州」「去北京」）；没提到就填"待定"，绝不编造或从其他词猜测城市。
相对时间（如「下周」「明天」「下周一」「后天」）必须按「今天」推算成具体 YYYY-MM-DD，不要填"待定"；完全没提日期才填"待定"。
示例：{{"from_city": "北京", "to_city": "杭州", "start_date": "2026-08-20", "duration_days": 3, "people_count": 2, "purpose": "拜访客户", "return_date": "", "transport_pref": "高铁", "hotel_pref": "无", "budget_pref": "中等", "date_is_vague": false}}，
模糊示例：{{"from_city": "北京", "to_city": "杭州", "start_date": "2026-08-17", "duration_days": 3, "people_count": 1, "purpose": "开会", "return_date": "", "transport_pref": "无", "hotel_pref": "无", "budget_pref": "中等", "date_is_vague": true}}（用户只说了「下周」）""",
        ),
        (
            "human",
            "今天是 {today}。\n用户输入：{input}\n对话上文（仅用于补全省略信息，如本轮没重复说过的城市）：{recent}",
        ),
    ]
)

plan_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是资深差旅规划师，输出严格 JSON。基于差旅要素生成企业差旅行程。
约束：
- 天数与要素一致；每天包含 transport、hotel、activities、notes 四个字段
- 人数、出行目的、交通偏好影响安排：多人出行注意订房/订票数量，公务目的安排会议/拜访，旅游目的安排景点
- 交通方式符合城市间距离；活动含公务安排和用餐建议
- 住宿必须符合用户的【历史偏好】，偏好没提到再按预算安排；酒店给品牌/档位即可
- reasons：安排理由列表，每项一句，涵盖政策约束、用户偏好、交通合理性，例如："住宿按差旅政策一线城市不超过500元/晚"、"考虑你不吃辣的偏好安排清淡餐饮"
- summary 是给用户看的中文总结（不含 JSON）

字段形状必须严格如下（都是简单值，禁止嵌套对象！）：
- transport：一句话字符串，如 "高铁（具体车次和时间以12306实时查询为准）"
- hotel：字符串，如 "全季酒店（杭州西湖店）"；最后一天返程写 "无（当晚返程）"
- 禁止编造车次、发车时间、到达时间、余票或票价；没有实时票务结果时只能写“以12306为准”
- activities：字符串数组，每项一句，如 "14:00-17:00 公务：拜访客户公司"、"18:30-20:00 用餐：与客户晚餐"
- notes：字符串，一两句备注

输出键名严格为英文：days（数组，每项键名 date/transport/hotel/activities/notes）、summary、reasons（字符串数组）。""",
        ),
        (
            "human",
            "差旅要素：{trip_json}\n用户历史偏好：{prefs}\n公司差旅政策/标准：{policy}\n历史行程参考：{history_ref}\n目的地/安全/绿色出行提示（仅作注意事项，不得编造）：{guidance}\n用户原话：{user_input}",
        ),
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


# 未知城市/日期哨兵族：提取 LLM 可能输出多个变体（prompt 要求「待定」但有方差），
# 归一化后所有下游（缺项检查/常驻补全/记忆/历史显示）看到同一哨兵
_UNKNOWN_CITIES = ("待定", "未知", "出差", "无")

# 纯城市名补全兜底：排除含方向/回复/时间词的表述（那是完整句，交给 LLM），
# 排除含数字（「4天」「10月8日」不是城市）——只认「临沂」「北京」这类纯城市名
_CITY_REPLY_WORDS = (
    "去",
    "从",
    "到",
    "出发",
    "前往",
    "回",
    "飞",
    "坐",
    "乘",
    "转",
    "对",
    "好",
    "行",
    "可以",
    "是的",
    "不用",
    "算了",
    "取消",
    "没有",
    "有",
    "明天",
    "后天",
    "今天",
    "下周",
    "星期",
    "嗯",
    "哦",
)


def _looks_like_city_name(text: str) -> str | None:
    """启发式：纯城市名（2-4 字，可带「市」后缀）；非城市表述返回 None"""
    t = text.strip().rstrip("。！？!?，,、").strip()
    if not t or any(w in t for w in _CITY_REPLY_WORDS) or any(c.isdigit() for c in t):
        return None
    if t.endswith("市"):
        t = t[:-1]
    return t if 2 <= len(t) <= 4 else None


def _missing(req: TripRequest) -> list[str]:
    """检查必填要素缺失，返回缺失清单（基础项 E：缺失信息提示）"""
    miss = []
    if not req.to_city or req.to_city in _UNKNOWN_CITIES:
        miss.append("目的城市")
    if not req.from_city or req.from_city in _UNKNOWN_CITIES:
        miss.append("出发城市")
    if req.start_date in ("待定", ""):
        miss.append("出发日期")
    if not isinstance(req.duration_days, int) or req.duration_days <= 0:
        miss.append("出差天数")
    return miss


def _days_between(start: str, end: str) -> int | None:
    """YYYY-MM-DD 日期差（含首尾天数），解析失败返回 None"""
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    except ValueError:
        return None


def plan(
    user_input: str,
    *,
    session_id: str = "default",
    recent: str = "",
    upstream: dict | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> PlanResult | NeedsInfo | ValidationFailure:
    """编排：提取 → 常驻城市补全 → 缺项检查（短路）→ 生成 → 写回长期记忆

    recent：对话上文（多轮要素延续，如用户补齐缺项时不再重复说过的地方）；
    upstream：collect-then-compose 收集阶段注入的上游上下文
    （{policy: 公司差旅政策/标准文本, history_ref: 历史行程参考}，缺省槽位为「无」）；
    顺序是产品行为（ADR-0003），勿改。
    """
    req = _extract_model().invoke({"input": user_input, "today": _today_cn(), "recent": recent or "无"})
    assert isinstance(req, TripRequest)
    if cancelled and cancelled():
        raise RuntimeError("请求已取消")
    # 哨兵归一化：先把「无/未知/出差」统一成「待定」，再走补全/缺项检查
    # （否则「无」会绕过两者，带着无意义城市进生成 → 规划 LLM 默认当北京，记忆却记「无」，历史显示不一致）
    if req.from_city in _UNKNOWN_CITIES:
        req.from_city = "待定"
    if req.to_city in _UNKNOWN_CITIES:
        req.to_city = "待定"
    # 纯城市名补全兜底（确定性规则，LLM 对「追问后回纯城市名」提取不稳，实测同输入多次 from=待定）：
    # 一个城市已确定、另一个缺失时，本轮输入若是纯城市名 → 直接补缺失槽，不再追问
    if req.to_city not in _UNKNOWN_CITIES and req.from_city in _UNKNOWN_CITIES:
        city = _looks_like_city_name(user_input)
        if city:
            req.from_city = city
    elif req.from_city not in _UNKNOWN_CITIES and req.to_city in _UNKNOWN_CITIES:
        city = _looks_like_city_name(user_input)
        if city:
            req.to_city = city
    # 天数哨兵归一化：LLM 可能输出「待定/无」字符串（曾致 pydantic 校验崩溃），统一成 0
    if isinstance(req.duration_days, str):
        req.duration_days = 0
    # 人数哨兵归一化：LLM 可能输出「待定/无」字符串或 0/负数 → 统一成 1（单人）
    if isinstance(req.people_count, str):
        try:
            req.people_count = int(req.people_count)
        except ValueError:
            req.people_count = 1
    if not isinstance(req.people_count, int) or req.people_count <= 0:
        req.people_count = 1
    # 返程日期推算天数：用户给了明确返程日期但没说天数 → 用日期差补 duration_days
    if (not isinstance(req.duration_days, int) or req.duration_days <= 0) and req.return_date:
        days = _days_between(req.start_date, req.return_date)
        if days and days > 0:
            req.duration_days = days
    # 常驻城市补全：先于缺项检查（"用户没说出发城市但记忆里有"不算缺项）
    hc = get_home_city(session_id=session_id)
    if (not req.from_city or req.from_city in _UNKNOWN_CITIES) and hc:
        req.from_city = hc
    miss = _missing(req)
    if miss:
        return NeedsInfo(missing=miss, request=req)
    prefs = get_preferences(session_id=session_id)
    prefs_text = "；".join(f"{p['category']}:{p['content']}" for p in prefs) or "无"
    upstream = upstream or {}
    # 本轮偏好（collect 串行阶段结构化提取）：并入历史偏好，消除多意图并行「偏好写库 vs 行程读偏好」竞态。
    # 上游缺失（直接调用/旧路径）时无本轮偏好 → 回退纯历史偏好，行为兼容。
    turn_prefs = upstream.get("prefs_turn") or ""
    if turn_prefs:
        prefs_text = (
            f"{prefs_text}\n本轮陈述偏好：{turn_prefs}" if prefs_text != "无" else f"本轮陈述偏好：{turn_prefs}"
        )
    policy_context = upstream.get("policy_context")
    policy_status = getattr(policy_context, "status", "not_found")
    policy_prompt = upstream.get("policy") or "未检索到相关公司政策；不得引用或推断政策金额、限额、标准或审批时限。"
    if policy_status == "unavailable":
        policy_prompt = "政策服务当前不可用；不得引用或推断政策金额、限额、标准或审批时限。"
    if cancelled and cancelled():
        raise RuntimeError("请求已取消")
    plan = _plan_model().invoke(
        {
            "trip_json": req.model_dump_json(),
            "prefs": prefs_text,
            "policy": policy_prompt,
            "history_ref": upstream.get("history_ref") or "无",
            "guidance": upstream.get("guidance") or "无",
            "user_input": user_input,
        }
    )
    assert isinstance(plan, ItineraryPlan)
    # 静态参考数据不得伪装成实时票务结果：统一清理模型生成的具体车次/时刻。
    if req.transport_pref in ("无", "高铁"):
        for day in plan.days:
            if any(token in day.transport for token in ("高铁", "动车", "火车")):
                day.transport = "高铁（具体车次和时间以12306实时查询为准）"
    # 生成后、写回前做确定性验证：日期/天数/政策证据不满足时不污染历史记忆。
    from xiao_wen.validation import validate_trip

    policy_text = upstream.get("policy") or ""
    evidence_ids = tuple(upstream.get("policy_evidence_ids") or ())
    budget = estimate_budget(req)
    validation = validate_trip(
        req,
        plan,
        policy_text=policy_text,
        evidence_ids=evidence_ids,
        policy_context=policy_context,
        budget=budget,
    )
    if validation.blocking_issues:
        return ValidationFailure(issues=[issue.message for issue in validation.blocking_issues])
    # 写库前剔除无效天数（0/缺）：facts 缺 duration_days = 旧记录缺天数语义，
    # 差旅统计按「字段缺失」计 skipped_days，不被 0 污染平均天数
    facts = req.model_dump()
    if not req.duration_days:
        facts.pop("duration_days", None)
    facts["budget_estimate"] = budget
    if evidence_ids:
        facts["policy_evidence_ids"] = list(evidence_ids)
    if policy_context is not None:
        facts["policy_snapshot_id"] = getattr(policy_context, "snapshot_id", "")
    facts["validation_status"] = "passed"
    from xiao_wen.validation import VALIDATOR_VERSION

    facts["validator_version"] = VALIDATOR_VERSION
    if cancelled and cancelled():
        raise RuntimeError("请求已取消")
    add_itinerary(facts, plan.summary, session_id=session_id)
    return PlanResult(plan=plan, request=req)


# ---- 展示（可读性格式化，测试锁定） ----

# 通用规划估算，不是供应商报价或公司政策。交通价格变化频繁，不做本地数字估算。
BUDGET_LEVELS = {
    "经济": {"hotel_per_night": 300, "meal_per_day": 120},
    "中等": {"hotel_per_night": 450, "meal_per_day": 200},
    "舒适": {"hotel_per_night": 700, "meal_per_day": 300},
}
DEFAULT_BUDGET_LEVEL = "中等"


def estimate_budget(req: TripRequest) -> dict:
    """确定性规划估算：只估住宿与餐饮，交通金额留给官方实时查询结果。"""
    assert isinstance(req.duration_days, int), "缺项检查后 duration 必为 int"
    people = req.people_count if isinstance(req.people_count, int) and req.people_count > 0 else 1
    nights = max(req.duration_days - 1, 0)  # 最后一天返程，住 (天数-1) 晚；一日往返 0 晚
    level = BUDGET_LEVELS.get(req.budget_pref, BUDGET_LEVELS[DEFAULT_BUDGET_LEVEL])
    budget_level = req.budget_pref if req.budget_pref in BUDGET_LEVELS else DEFAULT_BUDGET_LEVEL
    hotel_per_night = level["hotel_per_night"]
    rooms = (people + 1) // 2  # 双人标准间，向上取整
    hotel_cost = hotel_per_night * rooms * nights
    meal_per_day = level["meal_per_day"]
    meal_cost = meal_per_day * people * req.duration_days
    return {
        "budget_level": budget_level,
        "people": people,
        "rooms": rooms,
        "hotel_per_night": hotel_per_night,
        "nights": nights,
        "hotel_cost": hotel_cost,
        "meal_per_day": meal_per_day,
        "meal_cost": meal_cost,
        "total": hotel_cost + meal_cost,
    }


def format_budget(req: TripRequest) -> str:
    """格式化非政策规划估算；交通只引导至官方实时查询。"""
    b = estimate_budget(req)
    if b["nights"] == 0:
        hotel_line = "· 住宿：当日往返，无需住宿\n"
    else:
        rooms_suffix = "" if b["rooms"] == 1 else f" × {b['rooms']} 间"
        hotel_line = (
            f"· 住宿：{b['budget_level']}估算档 "
            f"{b['hotel_per_night']} 元/晚 × {b['nights']} 晚{rooms_suffix} ≈ {b['hotel_cost']} 元\n"
        )
    meal_people = "" if b["people"] == 1 else f" × {b['people']} 人"
    return (
        "💰 规划估算（非报价、非公司政策）：\n"
        "· 交通：不提供金额，请以 12306 官方页面的实时查询结果为准\n"
        f"{hotel_line}"
        f"· 餐饮：{b['meal_per_day']} 元/天{meal_people} × {req.duration_days} 天 ≈ {b['meal_cost']} 元\n"
        f"· 住宿与餐饮小计（不含交通）：约 {b['total']} 元"
    )


def _weather_is_usable(note: str) -> bool:
    """过滤天气工具的失败文案，避免把错误信息伪装成天气提醒。"""
    unavailable = ("查询天气失败", "不支持查询", "仅支持未来 7 天", "无法识别的日期")
    return bool(note.strip()) and not any(marker in note for marker in unavailable)


def _weather_needs_attention(note: str) -> bool:
    """对天气工具的可读结果做保守安全提示，不替天气服务编造预警。"""
    severe_words = ("大雨", "暴雨", "大雪", "暴雪", "雷暴", "冰雹", "大风", "台风", "雾")
    if any(word in note for word in severe_words):
        return True
    match = re.search(r"降水概率\s*(\d+)%", note)
    return bool(match and int(match.group(1)) >= 60)


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


@dataclass
class TripOutcome:
    """行程规划的完整产物（compose 阶段输出，供行程 Agent 透传）"""

    answer: str
    plan: dict | None  # 结构化 plan（含 date_is_vague），缺项时为 None
    task_update: dict | None = None


def _ticket_url(origin: str, destination: str, travel_date: str, return_date: str = "") -> tuple[str, str | None]:
    """统一生成 12306 官方预填链接。"""
    return build_ticket_url(origin, destination, travel_date, return_date)


def handle(
    user_input: str,
    *,
    session_id: str = "default",
    recent: str = "",
    upstream: dict | None = None,
    task_context: str = "",
    cancelled: Callable[[], bool] | None = None,
) -> TripOutcome:
    """行程规划完整编排入口（collect-then-compose 的 compose 阶段）：

    提取→补全→缺项→生成→写回（plan），并收口展示拼装——预算块、日期模糊提示、
    目的地天气提醒。行程 Agent 只做 state → 参数 → handle 的薄适配，不再理解展示细节。
    """
    from xiao_wen.web import get_weather

    r = plan(user_input, session_id=session_id, recent=recent, upstream=upstream, cancelled=cancelled)
    if isinstance(r, NeedsInfo):
        from xiao_wen.dialogue import task_update_set

        answer = needs_info_text(r)
        resume_context = "\n".join(
            part
            for part in (
                task_context.strip(),
                f"用户: {user_input}",
                f"助手: {answer}",
            )
            if part
        )
        return TripOutcome(
            answer=answer,
            plan=None,
            task_update=task_update_set(resume_context=resume_context, missing=r.missing),
        )
    if isinstance(r, ValidationFailure):
        return TripOutcome(
            answer="⚠️ 行程候选未通过一致性校验，暂未写入历史记录：\n· " + "\n· ".join(r.issues),
            plan=None,
        )
    answer = format_plan(r.plan)
    req = r.request
    policy_context = (upstream or {}).get("policy_context")
    policy_status = getattr(policy_context, "status", "not_found")
    if policy_status == "unavailable":
        answer += "\n\n⚠️ 公司政策服务暂时不可用；本行程未引用住宿标准、报销额度或审批时限，请在服务恢复后复核。"
    if req and req.date_is_vague:
        # 日期模糊（如只说了「下周」）：明示按推断日期安排，给用户确认/调整机会
        answer += (
            f"\n\n📅 你只说了出发时间的大致范围，我按 {req.start_date} 开始安排——"
            "如果实际日期不同，告诉我具体日期，我重新排。"
        )
    if req and policy_status != "unavailable":
        # 预算块：非政策规划估算；交通金额始终留给 12306 实时结果。
        with suppress(Exception):
            answer += f"\n\n{format_budget(req)}"
    if req and req.start_date not in ("待定", ""):
        cities = [req.from_city, req.to_city]
        weather_notes: list[tuple[str, str]] = []
        unavailable_cities: list[str] = []
        seen_cities: set[str] = set()
        for city in cities:
            if city in ("待定", "未知", "") or city in seen_cities:
                continue
            seen_cities.add(city)
            try:  # 天气是锦上添花：查不到不影响行程主答案，但要给用户诚实反馈
                note = get_weather.invoke({"city": city, "date": req.start_date})
                if _weather_is_usable(note):
                    weather_notes.append(("出发地" if city == req.from_city else "目的地", note))
                else:
                    unavailable_cities.append(city)
            except Exception:
                unavailable_cities.append(city)
        # 无论天气 API 是否可用，都不输出空标题；每个城市都给出可解释状态。
        weather_lines = [f"· {label}：{note}" for label, note in weather_notes]
        weather_lines.extend(f"· {city}：暂时无法获取天气，建议临近出发再次查询" for city in unavailable_cities)
        if weather_lines:
            answer += "\n\n🌤️ 目的地天气提醒（出行天气，出发日：" + req.start_date + "）：\n" + "\n".join(weather_lines)
            alerts = [note for _, note in weather_notes if _weather_needs_attention(note)]
            if alerts:
                answer += "\n\n⚠️ 异常天气安全提醒：请预留交通缓冲，关注航班/高铁和当地预警；必要时联系主管调整安排。"
    ticket_url = ""
    if (
        req
        and req.start_date not in ("待定", "")
        and req.from_city not in ("待定", "")
        and req.to_city not in ("待定", "")
    ):
        ticket_url, ticket_date_error = _ticket_url(req.from_city, req.to_city, req.start_date, req.return_date)
        answer += f"\n\n🎫 车票查询：\n· {req.from_city} → {req.to_city}\n· 出发日期：{req.start_date}"
        if req.return_date:
            answer += f"\n· 返程日期：{req.return_date}"
        if ticket_date_error:
            answer += f"\n· 暂未生成链接：{ticket_date_error}"
        elif ticket_url:
            answer += (
                f"\n· 前往铁路12306查询车次：{ticket_url}"
                "\n车站名称和电报码来自12306官方车站数据；请在12306页面确认实际车次、余票和票价；晓问不代购票。"
            )
        else:
            answer += "\n· 暂未生成链接：无法从12306官方车站数据确认对应车站，请补充具体车站。"
    if upstream:
        policy_sources = tuple(
            dict.fromkeys(
                item.get("source", "")
                for item in (upstream.get("sources") or [])
                if item.get("source", "")
                in {"01_travel_standards", "02_reimbursement_policy", "03_booking_guide", "04_faq", "06_platform_guide"}
            )
        )
        guidance_sources = tuple(dict.fromkeys(upstream.get("guidance_sources") or ()))
        if policy_sources:
            answer += "\n\n📌 政策依据：" + "、".join(policy_sources)
        if guidance_sources:
            answer += "\n\n📌 出差提示依据：" + "、".join(guidance_sources)
    plan_dict = r.plan.model_dump()
    plan_dict["date_is_vague"] = bool(req and req.date_is_vague)
    from xiao_wen.dialogue import task_update_clear

    return TripOutcome(answer=answer, plan=plan_dict, task_update=task_update_clear())
