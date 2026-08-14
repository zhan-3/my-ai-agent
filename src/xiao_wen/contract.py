"""HTTP 契约模型：FastAPI OpenAPI 的数据源（前端 openapi-typescript 生成 TS 类型的唯一来源）

与领域模型（trip_planner.ItineraryPlan 等）分离：
- 契约层允许字段缺失/多余容忍（pydantic 默认 extra=ignore）
- plan 结构不符契约时降级 None（答案文本仍在，前端展示层有回退通道）
"""

from pydantic import BaseModel


class TripDay(BaseModel):
    date: str
    transport: str
    hotel: str
    activities: list[str]
    notes: str


class TripPlan(BaseModel):
    """结构化行程（slice 1）：/api/chat → plan；日期模糊标记由行程 Agent 附加"""

    summary: str
    reasons: list[str]
    days: list[TripDay]
    date_is_vague: bool = False


class Preference(BaseModel):
    category: str
    content: str


class Itinerary(BaseModel):
    """历史行程摘要（记忆侧栏展示字段；容忍旧数据缺字段）"""

    start_date: str | None = None
    from_city: str | None = None
    to_city: str | None = None
    duration_days: int | None = None


class MemorySnapshot(BaseModel):
    preferences: list[Preference]
    itineraries: list[Itinerary]


class TravelStats(BaseModel):
    """差旅画像（确定性聚合，零 LLM；供 /api/stats 页面展示）"""

    has_data: bool
    trips: int
    total_days: int
    avg_days: float
    skipped_days: int
    top_cities: list[dict]
    years: list[dict]


def plan_or_none(raw: dict | None) -> TripPlan | None:
    """图产出的 plan dict → 契约 TripPlan；结构不符时降级 None（答案文本仍在，展示层有回退）"""
    if not raw:
        return None
    try:
        return TripPlan.model_validate(raw)
    except Exception:
        from xiao_wen.stability import logger

        logger.warning("plan 结构不符契约，降级为 None：%s", raw)
        return None
