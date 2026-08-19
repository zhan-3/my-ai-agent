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


class KnowledgeSource(BaseModel):
    """可追溯知识来源；与答案文本分离，供前端渲染来源卡片。"""

    evidence_id: str
    source: str
    section: str | None = None
    similarity: float | None = None
    text: str = ""


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
    """行程档案（记忆侧栏展示字段；容忍旧数据缺字段）"""

    id: int | None = None
    start_date: str | None = None
    from_city: str | None = None
    to_city: str | None = None
    duration_days: int | None = None
    summary: str | None = None
    status: str = "历史"
    conversation_id: str | None = None  # 该行程所在对话线程（前端箭头跳转续聊用）
    people_count: int | None = None
    return_date: str | None = None
    purpose: str | None = None


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
    upcoming_trips: int  # 未来规划条数（未发生，未计入画像；诚实标注）


class HistoryItinerary(BaseModel):
    """历史行程明细（结构化卡片；容忍旧数据缺字段）"""

    start_date: str | None = None
    from_city: str | None = None
    to_city: str | None = None
    duration_days: int | None = None
    summary: str | None = None
    status: str = "历史"  # 时空语义三态：历史 / 进行中 / 已规划


class HistoryResult(BaseModel):
    """历史查询结果（结构化；供聊天消息渲染行程卡片；空态由 answer 文本表达）"""

    itineraries: list[HistoryItinerary] = []
    preferences: list[Preference] = []
    direction: str = "历史"  # 查询方向：历史 / 计划（已规划的未来行程）


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


def stats_or_none(raw: dict | None) -> TravelStats | None:
    """图产出的 stats dict → 契约 TravelStats；结构不符时降级 None（同上）"""
    if not raw:
        return None
    try:
        return TravelStats.model_validate(raw)
    except Exception:
        from xiao_wen.stability import logger

        logger.warning("stats 结构不符契约，降级为 None：%s", raw)
        return None


def history_or_none(raw: dict | None) -> HistoryResult | None:
    """图产出的 history dict → 契约 HistoryResult；结构不符时降级 None（同上）"""
    if not raw:
        return None
    try:
        return HistoryResult.model_validate(raw)
    except Exception:
        from xiao_wen.stability import logger

        logger.warning("history 结构不符契约，降级为 None：%s", raw)
        return None
