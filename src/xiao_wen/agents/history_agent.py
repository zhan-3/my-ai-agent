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
    "查询历史行程/偏好/对话的记录明细（可按城市、日期、住宿类型筛选）"
    "——查单次或筛选明细找这里；问汇总统计（共几次、总天数、常去哪）不是明细查询"
)

from xiao_wen.memory import get_itineraries, get_preferences  # noqa: E402

# 问题关键词 → 查询方向（无 user_input 时视为综合查询，向后兼容）
_TRIP_WORDS = ("行程", "出差", "去哪", "路线", "计划", "安排", "游记", "记录", "订单", "消费", "日期", "入住")
_PREF_WORDS = ("偏好", "习惯", "常住", "记忆", "喜欢", "不吃", "口味", "住宿", "忌口")

# 城市词表（与 trip_planner 城市分级一致）：问题提到城市 → 按城市过滤行程
_CITIES = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "杭州",
    "南京",
    "成都",
    "武汉",
    "西安",
    "重庆",
    "天津",
    "苏州",
    "长沙",
    "郑州",
)


def _mentioned_cities(q: str) -> list[str]:
    """问题里提到的城市（按词表匹配，保持输入顺序）"""
    return [c for c in _CITIES if c in q]


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
    sid = state.get("session_id", "default")
    q = (state.get("user_input") or "").strip()
    prefs = get_preferences(session_id=sid)
    its = get_itineraries(session_id=sid)

    cities = _mentioned_cities(q)
    trip_hit = any(w in q for w in _TRIP_WORDS)
    pref_hit = any(w in q for w in _PREF_WORDS)
    # 都没命中（纯筛选/指代/追问句）→ 综合：两者都答（空回复是最大的失败）
    want_trip = (not q) or trip_hit or not pref_hit
    want_pref = (not q) or pref_hit or not trip_hit

    parts: list[str] = []
    if want_trip:
        matched = [it for it in its if _itinerary_matches(it, cities)]
        if matched:
            lines = ["🗂️ 历史行程："]
            for it in reversed(matched[-5:]):  # 最多显示最近 5 条
                lines.append(
                    f"· {it.get('start_date', '?')} {it.get('from_city', '?')}→{it.get('to_city', '?')}，"
                    f"{it.get('duration_days', '?')}天：{it.get('summary', '')}"
                )
            parts.append("\n".join(lines))
        elif cities:
            parts.append(f"📭 未找到{cities[0]}的记录，建议换个条件（日期/城市/住宿类型）再试。")
        else:
            parts.append("📭 暂无历史行程记录。")
    if want_pref:
        if prefs:
            parts.append("💡 记忆偏好：" + "；".join(f"{p['category']} {p['content']}" for p in prefs))
        else:
            parts.append("💡 暂无记忆偏好。")
    return {"answer": "\n\n".join(parts)}
