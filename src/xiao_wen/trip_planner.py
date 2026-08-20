"""行程规划管线（ADR-0003）：要素提取 → 常驻城市补全 → 缺项检查 → 生成 → 写回 → 格式化

单一接口 plan(user_input) -> PlanResult | NeedsInfo（判别式返回，缺项清单可测）。
编排顺序是产品行为，勿改：常驻城市补全**先于**缺项检查（“用户没说出发城市但记忆里有”
不算缺项）；缺项短路不调生成；写回发生在生成成功后。
"""

# ruff: noqa: E501 —— 本模块是 prompt 密集模块：发给 LLM 的提示词内容行
# （要素示例、约束、reasons 说明）天然超行宽，拆分会改变提示词（换行=内容）。
import logging
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from xiao_wen import llm
from xiao_wen.memory import add_or_update_preference, get_home_city, get_preferences, save_trip
from xiao_wen.reference_data import CITY_COORDS

logger = logging.getLogger("xiao_wen.trip_planner")

# 相对日期解析：给提取器注入「今天」（含周几），让「下周/明天」能推算成具体日期
_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 修改已有行程的触发词（改期/改人数/改细节等）；agent_loop 门禁与 itinerary_agent 续接共用，勿漂移
TRIP_MODIFY_WORDS = ("改成", "改为", "换成", "换为", "改期", "调整", "变更", "改一下")


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
    mixed_gender: bool = Field(default=False, description="异性同行（如「一男一女」）需分房；由代码填充，不依赖提取")


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
    plan: ItineraryPlan
    request: TripRequest | None = None
    memory_writes: list[dict] = field(default_factory=list)
    home_city: str = ""  # 本轮声明并采纳的常驻城市（未声明/与已有相同为空串）


@dataclass
class NeedsInfo:
    missing: list[str]  # 缺失要素清单（基础项 E：缺项提示）
    request: TripRequest | None = None


@dataclass
class ValidationFailure:
    """候选行程未通过运行时验证；失败结果不得写回长期记忆。"""

    issues: list[str]
    request: TripRequest | None = None  # 保留提取结果，供校验失败后缺项续接（如「天数不一致」）


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
- 人数、出行目的、交通偏好影响安排：多人出行（people_count > 1）注意订房/订票数量，summary 和 reasons 必须明确写出人数与房间/票数
- 异性同行（用户说「一男一女」「男女各一人」等）必须分房：订 2 间单间或 2 间房，不得安排 1 间双床房；summary 明确写「分房（2 间）」
- 交通方式符合城市间距离
- 住宿必须符合用户的【历史偏好】，偏好没提到再按预算安排；酒店给品牌/档位即可
- 目的地为境外城市（非中国大陆，如纽约、伦敦、东京、香港、澳门、台北等）时：住宿/餐饮不得引用境内人民币标准（「一线/二线/三线城市 X 元/晚」或 500/400/300 元这类数字），reasons 不得写「按差旅政策一线城市不超过500元/晚」这类金额，统一写「住宿/餐饮标准以当地差旅政策为准」；hotel 只写品牌/档位（如「当地商务酒店」），不得编造具体门店名
- reasons：安排理由列表，每项一句，只写事实依据（政策约束、用户偏好、交通合理性、时差等），不得编造用户没说过的活动内容（如「安排了客户拜访」「安排了商务会议」）
- summary 是给用户看的中文总结（不含 JSON）；只写事实（城市、日期、天数、人数、交通、住宿、出行目的）；用户明确说了目的（purpose 非空）才写「本次为XX出差」，没说就不编造；**不得声称系统已执行任何动作**（如「已记录/已保存/已添加您的偏好或历史」）；偏好与历史记录由程序负责，会在行程回答之外提示；出行人数>1时 summary 必须明确写出人数与订房数量

字段形状必须严格如下（都是简单值，禁止嵌套对象！）：
- transport：一句话字符串，只填交通方式本身，如 "高铁（具体车次和时间以晓问商旅平台实时查询为准）" 或 "航班（具体航班和时间以晓问商旅平台实时查询为准）"；不要带「去程/返程」前缀（程序会自动加）；仅首日填去程交通、末日填返程交通，中间日填空字符串 ""（单目的地无换乘）
- hotel：字符串，如 "全季酒店（杭州西湖店）"；仅首日填全程住宿，后续天填 ""；末日返程当天填 "无（当晚返程）"
- 禁止编造车次、发车时间、到达时间、余票或票价；没有实时票务结果时只能写"以晓问商旅平台实时查询为准"
- activities：字符串数组，每项一句，只写「用户明确说过的安排」+ 必要事实项；禁止编造用户没说过的活动（如「拜访客户公司」「商务会议」），禁止精确时间戳（如「09:00-12:00」）：
  · 首日写「抵达后入住酒店」，末日写「返程」
  · 不要写「用餐/饮食」建议（餐饮报销标准在预算块、饮食偏好由程序单独提示，均不逐日重复）
  · 用户明确说了目的（purpose 非空，如「拜访客户」「开会」）时：短差（≤5 天）在停留日写一条该安排；天数较多（>5 天）时中间停留日 activities 留空，或只写用户明确安排了具体日期的活动，不要逐日重复写「出差」「工作」「办公」这类泛化活动（程序会在展示层折叠）
- notes：字符串，一两句通用备注（如调整时差、带好证件），不编造具体活动

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

# 交通与距离的确定性匹配阈值（公里）：
# ≤ _TRAIN_PREFERRED_KM 且用户未声明交通偏好时，默认高铁（依据《差旅标准》环保线「300km 内
# 鼓励高铁而非飞机」+ 常识扩展）；超过该距离不干预（LLM 按距离自由，远程航班合理）。
_TRAIN_PREFERRED_KM = 700


def _distance_km(city_a: str, city_b: str) -> float | None:
    """两城市直线距离（Haversine，公里）。任一城市未收录（reference_data.CITY_COORDS）
    返回 None → 调用方跳过确定性修正（避免把未收录城市误判成短途）。"""
    a = CITY_COORDS.get(city_a)
    b = CITY_COORDS.get(city_b)
    if not a or not b:
        return None
    from math import asin, cos, radians, sin, sqrt

    lat1, lon1 = a
    lat2, lon2 = b
    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(h))


# 纯城市名补全兜底：排除含方向/回复/时间词的表述（那是完整句，交给 LLM），
# 排除含数字（「4天」「10月8日」不是城市）——只认「临沂」「北京」这类纯城市名
_HOME_MARKERS = ("常住", "定居", "家在", "目前住在", "住在")


def _detect_home_city(user_input: str) -> str:
    """识别「常住/定居/家在/目前住在」声明的常驻城市；未声明返回空串。

    命中即视为用户对常驻城市的事实声明（如「从常住地临沂」）。行程规划把该城市沉淀为
    偏好写回（延迟写），回答中的「已记录常驻城市」由代码在真实落库后追加，禁止模型编造。
    """
    if not any(marker in user_input for marker in _HOME_MARKERS):
        return ""
    for marker in _HOME_MARKERS:
        idx = user_input.find(marker)
        if idx < 0:
            continue
        tail = user_input[idx + len(marker) :]
        if tail.startswith("地"):
            tail = tail[1:]
        from xiao_wen.reference_data import KNOWN_CITIES

        t = tail.lstrip(" ，,、:：")
        for city in sorted(KNOWN_CITIES, key=len, reverse=True):
            if t.startswith(city):
                return city
        candidate = t[:2]  # 已知城市之外（如临沂）：取 2 字城市名
        if len(candidate) == 2 and candidate not in _CITY_REPLY_WORDS and not any(c.isdigit() for c in candidate):
            return candidate
    return ""


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


def _mixed_gender(text: str) -> bool:
    """异性同行信号（「一男一女」「男女各一人」「2男1女」等）→ 分房（每人一间），不定双床房。"""
    if any(word in text for word in ("一男一女", "男女各", "异性", "一男", "一女", "男同事", "女同事")):
        return True
    # 数字+性别组合：如「2男1女」「1女2男」「3男2女」（提取 LLM 只填 people_count，性别组合不依赖 LLM）
    return bool(re.search(r"\d+\s*男[^，。,.！？；]{0,6}\d+\s*女|\d+\s*女[^，。,.！？；]{0,6}\d+\s*男", text))


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
    thread_id: str | None = None,
    recent: str = "",
    upstream: dict | None = None,
    cancelled: Callable[[], bool] | None = None,
    defer_write: bool = False,
    trip_id: int | None = None,
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
    # 异性同行：代码填充（提取 LLM 只填 people_count，「一男一女」的分房语义不依赖 LLM）
    req.mixed_gender = _mixed_gender(user_input) or _mixed_gender(recent)
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
    # 「待N晚/住N晚/N晚」语义归一化（确定性规则，不依赖 LLM）：
    # 8/25 出发「待 2 晚」= 25、26 两晚 + 27 返程 = 3 天。LLM 常把「待2晚」提取成 2 天，
    # 与候选行程（3 天）校验冲突 → 校验失败不落库 → 用户确认缺项时门禁死循环。
    night_m = re.search(r"(?:待|住|共)?\s*(\d+)\s*晚", user_input or "")
    if night_m and isinstance(req.duration_days, int) and req.duration_days == int(night_m.group(1)):
        req.duration_days += 1
    # 常驻城市补全：先于缺项检查（"用户没说出发城市但记忆里有"不算缺项）
    hc = get_home_city(session_id=session_id)
    if (not req.from_city or req.from_city in _UNKNOWN_CITIES) and hc:
        req.from_city = hc
    miss = _missing(req)
    if miss:
        return NeedsInfo(missing=miss, request=req)
    # 过去日期拦截：行程只规划今天及未来；改期到过去没有意义（历史档案是只读的，不通过规划补录）。
    # 提取后、生成前拦截，避免花 LLM 生成一条过去日期的行程再落库成 completed。
    try:
        if date.fromisoformat(req.start_date) < date.today():
            return ValidationFailure(issues=[f"出发日期 {req.start_date} 已过，请指定今天或之后的日期"], request=req)
    except (ValueError, TypeError):
        pass
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
    # 境外目的地：显式告知生成 LLM 不得套境内人民币标准（海外城市会被 _city_tier 误判三线，产出「500 元/晚」类编造）
    from xiao_wen.web import is_overseas

    if is_overseas(req.to_city):
        policy_prompt += (
            "；目的地为境外城市，住宿/餐饮标准以当地差旅政策为准，不得引用境内人民币标准（一线/二线/三线 X 元/晚）"
        )
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
                day.transport = "高铁（具体车次和时间以晓问商旅平台实时查询为准）"
    # 交通方式与距离的确定性匹配（LLM「交通符合城市间距离」是软约束，实测把 550km 的
    # 临沂→北京判成「较远」选航班）：用户未声明偏好且两端城市可查时，短途按
    # 《差旅标准》环保线降级为高铁，并把 LLM 的「选航班」理由一并纠正。用户明说偏好不覆盖。
    if req.transport_pref == "无":
        km = _distance_km(req.from_city, req.to_city)
        if km is not None and km <= _TRAIN_PREFERRED_KM:
            for day in plan.days:
                if any(token in day.transport for token in ("航班", "飞机", "航空")):
                    day.transport = "高铁（具体车次和时间以晓问商旅平台实时查询为准）"
            if plan.reasons:
                plan.reasons = [r for r in plan.reasons if not any(token in r for token in ("航班", "飞机", "航空"))]
                plan.reasons.append(f"两地直线约 {km:.0f} 公里，属中短途，按公司环保倡议选择高铁")
    # 生成后、写回前做确定性验证：日期/天数/政策证据不满足时不污染历史记忆。
    from xiao_wen.validation import validate_trip

    policy_text = upstream.get("policy") or ""
    evidence_ids = tuple(upstream.get("policy_evidence_ids") or ())
    budget = estimate_budget(req, getattr(policy_context, "facts", ()))
    validation = validate_trip(
        req,
        plan,
        policy_text=policy_text,
        evidence_ids=evidence_ids,
        policy_context=policy_context,
        budget=budget,
    )
    if validation.blocking_issues:
        return ValidationFailure(issues=[issue.message for issue in validation.blocking_issues], request=req)
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
    memory_writes: list[dict] = []
    plan_dict = plan.model_dump()
    plan_dict["date_is_vague"] = bool(req.date_is_vague)
    if not defer_write:
        save_trip(
            facts,
            plan_dict,
            session_id=session_id,
            thread_id=thread_id,
            trip_id=trip_id,
            status="upcoming",
        )
    else:
        memory_writes.append(
            {"type": "trip", "facts": facts, "plan": plan_dict, "trip_id": trip_id, "thread_id": thread_id}
        )
    # 「从常住地X/我常住X/家在X」：常驻城市声明沉淀为偏好（写入与 itinerary 同一事务语义）
    home_city = ""
    declared = _detect_home_city(user_input)
    if declared and declared != hc:
        home_city = declared
        if defer_write:
            memory_writes.append({"type": "preference", "category": "常驻城市", "content": declared, "is_update": True})
        else:
            add_or_update_preference("常驻城市", declared, True, session_id=session_id)
    return PlanResult(plan=plan, request=req, memory_writes=memory_writes, home_city=home_city)


# ---- 展示（可读性格式化，测试锁定） ----

# 差旅住宿标准城市分级（依据 01 差旅标准文档：一线 4 城 / 二线省会与直辖市 / 其余三线及以下）
_TIER1_CITIES = ("北京", "上海", "广州", "深圳")
_TIER2_CITIES = (
    "天津",
    "重庆",
    "石家庄",
    "太原",
    "呼和浩特",
    "沈阳",
    "长春",
    "哈尔滨",
    "南京",
    "杭州",
    "合肥",
    "福州",
    "南昌",
    "济南",
    "郑州",
    "武汉",
    "长沙",
    "南宁",
    "海口",
    "成都",
    "贵阳",
    "昆明",
    "拉萨",
    "西安",
    "兰州",
    "西宁",
    "银川",
    "乌鲁木齐",
)


def _city_tier(city: str) -> str:
    """住宿标准档位分级：一线 4 城 / 二线省会与直辖市 / 其余三线及以下。"""
    if city in _TIER1_CITIES:
        return "一线"
    if city in _TIER2_CITIES:
        return "二线"
    return "三线"


def estimate_budget(req: TripRequest, facts: tuple = (), *, overseas: bool = False) -> dict:
    """确定性政策标准估算：住宿/餐饮金额读自 RAG 政策事实（hotel_rate/meal_rate）。

    交通金额不留本地估算。无有效事实时金额为 None，调用方不显示具体数字。
    overseas=True 时本地人民币标准不适用，金额一律不估算。
    """
    assert isinstance(req.duration_days, int), "缺项检查后 duration 必为 int"
    people = req.people_count if isinstance(req.people_count, int) and req.people_count > 0 else 1
    nights = max(req.duration_days - 1, 0)  # 最后一天返程，住 (天数-1) 晚；一日往返 0 晚
    rooms = people if req.mixed_gender else (people + 1) // 2  # 异性分房每人一间；否则双人标准间向上取整
    if overseas:
        return {
            "overseas": True,
            "city_tier": None,
            "people": people,
            "rooms": rooms,
            "hotel_rate": None,
            "nights": nights,
            "hotel_cost": None,
            "meal_rate": None,
            "meal_cost": None,
            "total": None,
        }
    tier = _city_tier(req.to_city)
    hotel_rate = next((f.value for f in facts if f.key == "hotel_rate" and f.scope.get("city_tier") == tier), None)
    meal_rate = next((f.value for f in facts if f.key == "meal_rate"), None)
    hotel_cost = hotel_rate * rooms * nights if hotel_rate is not None else None
    meal_cost = meal_rate * 2 * people * req.duration_days if meal_rate is not None else None
    total = hotel_cost + meal_cost if (hotel_cost is not None and meal_cost is not None) else None
    return {
        "overseas": False,
        "city_tier": tier,
        "people": people,
        "rooms": rooms,
        "hotel_rate": hotel_rate,
        "nights": nights,
        "hotel_cost": hotel_cost,
        "meal_rate": meal_rate,
        "meal_cost": meal_cost,
        "total": total,
    }


def format_budget(req: TripRequest, facts: tuple = (), *, overseas: bool | None = False) -> str:
    """格式化住宿/餐饮政策标准上限；交通只引导官方实时查询。

    金额读自 RAG 政策事实（hotel_rate/meal_rate），不是本地估算；无事实时不显示
    金额，引导以差旅标准/财务口径为准（避免两套数字漂移）。
    overseas=True（境外，含港澳台）：本地人民币标准不适用，标注当地差旅政策为准；
    overseas=None（无法判定）：不显示金额，避免误套人民币标准。
    """
    if overseas is None:
        return (
            "💰 预算参考：\n"
            "· 交通：不提供金额，请以晓问商旅平台的实时查询结果为准\n"
            "· 住宿/餐饮：无法确定当地差旅标准，请以差旅政策或财务口径为准"
        )
    if overseas:
        return (
            "💰 预算参考：\n"
            "· 交通：不提供金额，请以晓问商旅平台的实时查询结果为准\n"
            "· 住宿/餐饮：海外出行，标准请以当地差旅政策为准"
        )
    b = estimate_budget(req, facts)
    if b["hotel_rate"] is None or b["meal_rate"] is None:
        return (
            "💰 预算参考：\n"
            "· 交通：不提供金额，请以晓问商旅平台的实时查询结果为准\n"
            "· 住宿/餐饮：政策服务未提供有效标准数字，请以差旅标准或财务口径为准"
        )
    if b["nights"] == 0:
        hotel_line = "· 住宿：当日往返，无需住宿\n"
    else:
        rooms_suffix = "" if b["rooms"] == 1 else f" × {b['rooms']} 间"
        hotel_line = (
            f"· 住宿（{b['city_tier']}城市标准）：≤ {b['hotel_rate']} 元/晚 × {b['nights']} 晚"
            f"{rooms_suffix} ≈ {b['hotel_cost']} 元\n"
        )
    meal_people = "" if b["people"] == 1 else f" × {b['people']} 人"
    return (
        "💰 预算参考（按公司差旅标准上限估算，非报价）：\n"
        "· 交通：不提供金额，请以晓问商旅平台的实时查询结果为准\n"
        f"{hotel_line}"
        f"· 餐饮：≤ {b['meal_rate']} 元/餐 × 2 餐/天{meal_people} × {req.duration_days} 天 ≈ {b['meal_cost']} 元\n"
        f"· 住宿与餐饮合计（不含交通）：约 {b['total']} 元"
    )


def _weather_window_days(start_date: str) -> int | None:
    """出发日距今天的天数（未来 0~6 天在天气工具 7 天预报窗口内）；无法解析返回 None"""
    try:
        return (date.fromisoformat(start_date) - date.today()).days
    except (ValueError, TypeError):
        return None


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


def _emergency_note() -> str:
    """恶劣天气触发的应急提醒：优先引 05 应急文档的极端天气节，检索失败回退硬编码。"""
    from xiao_wen import rag

    with suppress(Exception):
        for ev in rag.retrieve_emergency("台风 暴雨 极端天气"):
            text = ev.text
            if not text:
                continue
            # 优先截取「台风/暴雨/极端天气」相关子节，避免命中整节「自然灾害」时从头截到地震。
            for marker in ("台风", "暴雨", "极端天气"):
                idx = text.find(marker)
                if idx >= 0:
                    text = text[idx:]
                    break
            text = _cut_section(text)
            if text:
                return "\n\n⚠️ 异常天气安全提醒：\n" + _format_emergency(text)
    return "\n\n⚠️ 异常天气安全提醒：请预留交通缓冲，关注航班/高铁和当地预警；必要时联系主管调整安排。"


def _format_emergency(text: str) -> str:
    """把 RAG chunk 粘连成单行的应急文本重新排成分条列表（chunk 换行已合并为空格）。

    原：「台风…  处理步骤： a) 提前… b) 如已… c) 如已在当地： - 待在室内 - 关注预警」
    后：「台风…\n处理步骤：\na) 提前…\nb) 如已…\nc) 如已在当地：\n  - 待在室内\n  - 关注预警」
    """
    text = re.sub(r"\s*处理步骤：\s*", "\n处理步骤：\n", text)
    text = re.sub(r"\s+(?=[a-z]\)\s)", "\n", text)  # 「 a) 」→ 换行
    text = re.sub(r"\s+(?=- )", "\n  ", text)  # 「 - 」→ 换行缩进
    return text.strip()


def _cut_section(text: str) -> str:
    """截到下一个编号小节标题之前，避免跨节截取（如极端天气节末尾混入「3. 疫情或传染病」）。

    小节标题形如「3. 疫情或传染病」「七、重要联系方式」。chunk 文本换行已被合并为空格，
    故用空白边界匹配编号标题（`[0-9]+.` 要求点后跟空白，避免误匹配「1.5小时」等小数）。
    """
    m = re.search(r"\s+(?:[0-9]+\.\s|[一二三四五六七八九十]+、)", text)
    if m:
        text = text[: m.start()]
    return text.strip()


def _strip_transport_prefix(s: str) -> str:
    """防御性清理 LLM 可能误加的「去程：/返程：」前缀（format_plan 会自己加）。"""
    for prefix in ("去程：", "去程:", "返程：", "返程:"):
        if s.startswith(prefix):
            return s[len(prefix) :].strip()
    return s


def _day_items(d: DayPlan) -> list[str]:
    """一天的展示要点（activities + notes），空的返回空列表。"""
    items = [a for a in d.activities if a]
    if d.notes:
        items.append(d.notes)
    return items


# 泛化活动：长差中间日这类「不是具体安排」的项视为空白（LLM 常把 purpose 逐日重复成「出差/工作」）
_GENERIC_ACTIVITIES = ("出差", "工作", "办公", "上班", "公务")


def _specific_activities(d: DayPlan) -> list[str]:
    """长差中间日只保留具体安排（拜访客户/开会等），泛化活动视为空白。"""
    return [a for a in d.activities if a and not any(g in a for g in _GENERIC_ACTIVITIES)]


def _diet_pref_line(session_id: str, turn_prefs: str = "") -> str | None:
    """从长期偏好 + 本轮陈述偏好提取餐饮偏好，生成一次性提示（不逐日重复）。"""
    contents: list[str] = []
    for p in get_preferences(session_id=session_id):
        if p.get("category") == "餐饮" and p.get("content"):
            contents.append(str(p["content"]).strip())
    if turn_prefs:
        for part in turn_prefs.split("；"):
            if part.startswith("餐饮:"):
                content = part.split(":", 1)[1].strip()
                if content:
                    contents.append(content)
    seen: set[str] = set()
    uniq: list[str] = []
    for c in contents:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return f"🍽️ 饮食偏好：{'；'.join(uniq)}" if uniq else None


def format_plan(plan: ItineraryPlan, diet_pref: str | None = None, purpose: str = "") -> str:
    """整体结构（ADR-0011 后不逐日切块）：去程/住宿/返程 + 每日要点。

    短差（≤5 天）逐日列要点；长差（>5 天）折叠空白停留日为一行（结合 purpose）。
    饮食偏好（diet_pref）只在住宿之后提示一次，不逐日重复。
    """
    lines = [f"📋 {plan.summary}", ""]
    if plan.reasons:
        lines.append("💡 安排理由：")
        for r in plan.reasons:
            lines.append(f"  · {r}")
        lines.append("")
    days = plan.days
    if days:
        first, last = days[0], days[-1]
        first_t = _strip_transport_prefix(first.transport)
        if first_t:
            lines.append(f"🚄 去程：{first_t}")
        if first.hotel and first.hotel != "无（当晚返程）":
            lines.append(f"🏨 住宿：{first.hotel}")
        if len(days) > 1:
            last_t = _strip_transport_prefix(last.transport)
            if last_t:
                lines.append(f"🚄 返程：{last_t}")
        if diet_pref:
            lines.append(diet_pref)
        if len(days) > 5:
            # 长差：首日 + 有具体安排的日子 + 末日；泛化/空白中间日折叠成一行
            daily: list[str] = []
            blank = 0
            first_items = _day_items(first)
            if first_items:
                daily.append(f"· {first.date} {'；'.join(first_items)}")
            for d in days[1:-1]:
                items = _specific_activities(d)
                if items:
                    daily.append(f"· {d.date} {'；'.join(items)}")
                else:
                    blank += 1
            if len(days) > 1:
                last_items = _day_items(last)
                if last_items:
                    daily.append(f"· {last.date} {'；'.join(last_items)}")
            if daily:
                lines.append("📌 行程安排：")
                lines.extend(daily)
            if blank:
                lines.append(f"· 其余 {blank} 天：{'继续' + purpose if purpose else '无特别安排'}")
        else:
            daily = []
            for d in days:
                items = _day_items(d)
                if items:
                    daily.append(f"· {d.date} {'；'.join(items)}")
            if daily:
                lines.append("📌 行程安排：")
                lines.extend(daily)
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
    plan: dict | None
    task_update: dict | None = None
    memory_writes: list[dict] = field(default_factory=list)


def handle(
    user_input: str,
    *,
    session_id: str = "default",
    thread_id: str | None = None,
    recent: str = "",
    upstream: dict | None = None,
    task_context: str = "",
    cancelled: Callable[[], bool] | None = None,
    defer_write: bool = False,
    trip_id: int | None = None,
) -> TripOutcome:
    """行程规划完整编排入口（collect-then-compose 的 compose 阶段）：

    提取→补全→缺项→生成→写回（plan），并收口展示拼装——预算块、日期模糊提示、
    目的地天气提醒。行程 Agent 只做 state → 参数 → handle 的薄适配，不再理解展示细节。
    """
    from xiao_wen.web import get_weather

    logger.info("行程规划 handle session=%s trip_id=%s", session_id, trip_id)

    r = plan(
        user_input,
        session_id=session_id,
        thread_id=thread_id,
        recent=recent,
        upstream=upstream,
        cancelled=cancelled,
        defer_write=defer_write,
        trip_id=trip_id,
    )
    if isinstance(r, NeedsInfo):
        logger.info("行程缺项 missing=%s", r.missing)
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
            task_update=task_update_set(
                resume_context=resume_context,
                missing=r.missing,
                trip_id=trip_id,
                facts=r.request.model_dump() if r.request else None,
            ),
        )
    if isinstance(r, ValidationFailure):
        logger.warning("行程校验失败 issues=%s", r.issues)
        from xiao_wen.dialogue import task_update_set

        answer = "⚠️ 行程候选未通过一致性校验，暂未写入历史记录：\n· " + "\n· ".join(r.issues)
        # 校验失败也落库为可续接缺项（如「天数不一致」→ 用户确认后门禁放行），
        # 避免「确认消息既不是新行程又没有活跃缺项」导致 Agent Loop 门禁死循环。
        task_update = None
        if any("天" in str(issue) for issue in r.issues):
            resume_context = "\n".join(
                part
                for part in (
                    task_context.strip(),
                    f"用户: {user_input}",
                    f"助手: {answer}",
                )
                if part
            )
            task_update = task_update_set(
                resume_context=resume_context,
                missing=["出差天数"],
                trip_id=trip_id,
                facts=r.request.model_dump() if r.request else None,
            )
        return TripOutcome(
            answer=answer,
            plan=None,
            task_update=task_update,
        )
    req = r.request
    diet = _diet_pref_line(session_id, (upstream or {}).get("prefs_turn") or "")
    answer = format_plan(r.plan, diet_pref=diet, purpose=(req.purpose if req else ""))
    if req and isinstance(req.people_count, int) and req.people_count > 1:
        rooms = req.people_count if req.mixed_gender else (req.people_count + 1) // 2
        answer = f"👥 本次出行 {req.people_count} 人（住宿按 {rooms} 间房估算）\n\n{answer}"
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
    if req and req.to_city not in ("待定", "未知", ""):
        # 时差提醒：目的地跨时区才提示（中国统一时区，境内/港澳台时差均为 0）
        from xiao_wen.web import time_diff_from_beijing

        diff = time_diff_from_beijing(req.to_city)
        if diff is not None and abs(diff) > 0.01:
            direction = "早" if diff > 0 else "晚"
            answer += (
                f"\n\n⏰ 时差提醒：目的地{req.to_city}比北京时间{direction}{abs(diff):.0f}小时，建议出发前调整作息。"
            )
    if req and policy_status != "unavailable":
        # 预算块：政策标准上限（读 RAG facts）；境外不套本地人民币标准，交通金额留给晓问商旅平台实时结果。
        from xiao_wen.web import is_overseas

        with suppress(Exception):
            overseas = is_overseas(req.to_city)
            answer += f"\n\n{format_budget(req, getattr(policy_context, 'facts', ()), overseas=overseas)}"
    # 天气/空气都仅当出发日在未来 7 天窗口内才查（weather 工具仅支持未来 7 天；空气是「当前」数据，
    # 远日期时当前空气与出行日无关）。更远日期静默跳过，避免「暂时无法获取」刷屏。
    days_until = _weather_window_days(req.start_date) if (req and req.start_date not in ("待定", "")) else None
    if req and days_until is not None and 0 <= days_until <= 6:
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
                answer += _emergency_note()
    if req and req.to_city not in ("待定", "未知", "") and days_until is not None and 0 <= days_until <= 6:
        # 空气提醒：与天气同窗口（当前数据），境内境外都查，PM2.5 超标（≥75）才提示，不刷屏
        from xiao_wen.web import get_air_quality

        try:
            aq = get_air_quality.invoke({"city": req.to_city, "date": req.start_date})
            m = re.search(r"PM2\.5\s*(\d+(?:\.\d+)?)", aq)
            if m and float(m.group(1)) >= 75:
                answer += f"\n\n😷 空气质量提醒：{aq}"
        except Exception as exc:
            logger.warning("空气质量查询失败（静默降级）：%s", exc)
    if req and policy_status != "unavailable":
        # 返程报销提醒：行程含返程时附时限一句（读 reimbursement_deadline fact），细节引导追问。
        has_return = bool(req.return_date) or (
            r.plan.days and ("返程" in (r.plan.days[-1].hotel or "") or "返程" in (r.plan.days[-1].transport or ""))
        )
        if has_return:
            deadline = next(
                (f.value for f in getattr(policy_context, "facts", ()) if f.key == "reimbursement_deadline"),
                None,
            )
            if deadline is not None:
                answer += f"\n\n💼 报销提醒：出差结束后 {deadline} 个自然日内提交报销；发票抬头等报销细节可随时问我。"
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

    writes = list(r.memory_writes)
    if r.home_city:
        answer += f"\n\n✅ 已记录您的常驻城市为{r.home_city}，后续出差默认从该城市出发。"
    # 生成成功：drafting→upcoming 由 save_trip(trip_id) 完成（同一事务落库）；不在此处 clear，
    # 否则会先删掉绑定 trip_id 的草稿，使 save_trip 更新落空（ADR-0011 一轮多规划语义）。
    return TripOutcome(answer=answer, plan=plan_dict, task_update=None, memory_writes=writes)
