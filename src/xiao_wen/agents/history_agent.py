"""内置子 Agent：历史查询（多 Agent 架构的子 Agent 实体）

读长期记忆（xiao_wen.memory）的偏好与历史行程。
修复（2026-08）：意图对齐——按问题关键词区分「行程向 / 偏好向 / 综合」，
只回答用户问的那一类；无记录时明确空态（「暂无历史行程记录」），
不再无差别倒出全部记忆造成答非所问。
修复（BUG-001）：
- 关键词扩展——「记录/订单/消费/日期/入住」等筛选与追问用词归行程向，
  避免追问句（如「还是没有杭州的记录」「能帮我找出来吗」）落到空回复；
- 城市过滤——问题提到城市（如「杭州的出差记录」）时按城市过滤行程，
  未命中给带城市名的引导空态（「未找到杭州的记录」），不再倒出全部行程；
- 空回复防御——行程/偏好关键词都没命中时按综合查询处理（两者都答），
  保证任意输入都有明确空态文案，绝不返回空串。
"""

INTENT = "历史查询"
DESCRIPTION = (
    "仅查询已保存的历史行程/偏好/对话记录明细（可按城市、日期、住宿类型筛选）"
    "——查单次或筛选明细找这里；问汇总统计（共几次、总天数、常去哪）不是明细查询；"
    "'帮我安排/规划/排/订'是规划请求，不是历史查询"
    "→ 历史查询。"
)

from xiao_wen.memory import get_itineraries, get_preferences  # noqa: E402
from xiao_wen.reference_data import KNOWN_CITIES  # noqa: E402

# 问题关键词 → 查询方向（无 user_input 时视为综合查询，向后兼容）
_TRIP_WORDS = ("行程", "出差", "去哪", "路线", "计划", "安排", "游记", "记录", "订单", "消费", "日期", "入住")
_PREF_WORDS = ("偏好", "习惯", "常住", "记忆", "喜欢", "不吃", "口味", "住宿", "忌口")
# 计划向词：问「接下来/安排/什么时候出发」→ 未来规划；其余行程词 → 历史（已发生）
_PLAN_WORDS = ("计划", "安排", "规划", "接下来", "下次", "什么时候", "出发", "即将", "将要", "准备", "待办")
# 历史向词：明确过去语义 → 只查已发生（past+ongoing）；与 _PLAN_WORDS 都未命中 →
# 中性（「最近有哪些行程」）→ 全部行程（三态一起展示，各自标注状态）
_PAST_WORDS = ("历史", "上次", "之前", "以前", "去过", "以往", "旧的", "过去的")

# 城市词表：白名单（有经纬度坐标的常用差旅城市）为基础；
# 问题提到城市 → 按城市过滤行程。只认白名单会漏掉临沂等非坐标表城市，
# 导致城市筛选失效（返回全部行程），故候选词表还需含历史行程里实际出现过的城市。
_CITY_PLACEHOLDERS = ("待定", "未知", "无", "出差")


def _mentioned_cities(q: str, itineraries: list[dict] | None = None) -> list[str]:
    """问题里提到的城市（白名单优先，历史行程城市兜底；按输入顺序去重）"""
    candidates = list(KNOWN_CITIES)
    for it in itineraries or []:
        for key in ("from_city", "to_city"):
            city = str(it.get(key, "")).strip()
            if city and city not in _CITY_PLACEHOLDERS and city not in candidates:
                candidates.append(city)
    return [c for c in candidates if c in q]


def _itinerary_matches(it: dict, cities: list[str]) -> bool:
    """行程是否命中城市：出发/目的任一命中即可（未知城市「待定/无」不参与匹配）"""
    if not cities:
        return True
    from_c = str(it.get("from_city", ""))
    to_c = str(it.get("to_city", ""))
    return any(c in from_c or c in to_c for c in cities)


def run(state) -> dict:
    """按问题类型回答记忆查询：行程 / 偏好 / 综合；无记录给明确空态

    - 提到城市 → 行程按城市过滤，未命中给带城市名的引导空态
    - 行程/偏好关键词都没命中 → 综合查询（两者都答），绝不返回空串
    """
    sid = state.get("user_id", state.get("session_id", "default"))
    q = (state.get("user_input") or "").strip()
    prefs = get_preferences(session_id=sid)
    its = get_itineraries(session_id=sid)

    # 时空语义（确定性规则，非 LLM）：问「计划/安排/什么时候出发」→ 未来规划；
    # 其余行程查询 → 已发生（历史）。分类逻辑与差旅画像共享单一实现。
    from xiao_wen.stats import classify

    cls = classify(its)
    plan_hit = any(w in q for w in _PLAN_WORDS)
    past_hit = any(w in q for w in _PAST_WORDS)

    cities = _mentioned_cities(q, its)
    trip_hit = any(w in q for w in _TRIP_WORDS)
    pref_hit = any(w in q for w in _PREF_WORDS)
    # 都没命中（纯筛选/指代/追问句）→ 综合：两者都答（空回复是最大的失败）
    want_trip = (not q) or trip_hit or not pref_hit
    want_pref = (not q) or pref_hit or not trip_hit

    parts: list[str] = []
    items: list[dict] = []  # 结构化行程（前端卡片）：status 标注时空语义三态
    direction = "历史"
    if want_trip:
        if plan_hit:
            pool, title, direction = cls["upcoming"], "📅 已规划的行程：", "计划"
        elif past_hit:
            pool, title, direction = cls["past"] + cls["ongoing"], "🗂️ 历史行程：", "历史"
        else:
            # 中性问法（「最近有哪些行程」）：三态全展示，每条自标状态；
            # 未来行程不能丢——它们也是「最近的行程”（修复：只问“行程”时 upcoming 消失）
            pool = cls["past"] + cls["ongoing"] + cls["upcoming"]
            title, direction = "📋 最近行程：", "全部"
        matched = [it for it in pool if _itinerary_matches(it, cities)]
        if matched:
            lines = [title]
            for it in reversed(matched[-5:]):  # 最多显示最近 5 条
                lines.append(
                    f"· {it.get('start_date', '?')} {it.get('from_city', '?')}→{it.get('to_city', '?')}，"
                    f"{it.get('duration_days', '?')}天：{it.get('summary', '')}"
                )
                if plan_hit or it in cls["upcoming"]:
                    status = "已规划"
                elif it in cls["ongoing"]:
                    status = "进行中"
                else:
                    status = "历史"
                items.append(
                    {
                        "start_date": it.get("start_date"),
                        "from_city": it.get("from_city"),
                        "to_city": it.get("to_city"),
                        "duration_days": it.get("duration_days"),
                        "summary": it.get("summary", ""),
                        "status": status,
                    }
                )
            parts.append("\n".join(lines))
        elif cities:
            parts.append(f"📭 未找到{cities[0]}的记录，建议换个条件（日期/城市/住宿类型）再试。")
        else:
            parts.append("📭 暂无历史行程记录。" if not plan_hit else "📭 暂无已规划的行程，先告诉我你的出差安排吧。")
    prefs_out: list[dict] = []
    if want_pref:
        if prefs:
            parts.append("💡 记忆偏好：" + "；".join(f"{p['category']} {p['content']}" for p in prefs))
            prefs_out = [{"category": p["category"], "content": p["content"]} for p in prefs]
        else:
            parts.append("💡 暂无记忆偏好。")
    # 结构化输出（前端渲染卡片；空查询不产出 → None，前端不渲染）
    history = {"itineraries": items, "preferences": prefs_out, "direction": direction} if items or prefs_out else None
    return {"answer": "\n\n".join(parts), "history": history}
