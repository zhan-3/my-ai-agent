"""内置子 Agent：历史查询（多 Agent 架构的子 Agent 实体）

读长期记忆（xiao_wen.memory）的偏好与历史行程。
修复（2026-08）：意图对齐——按问题关键词区分「行程向 / 偏好向 / 综合」，
只回答用户问的那一类；无记录时明确空态（「暂无历史行程记录」），
不再无差别倒出全部记忆造成答非所问。
"""

INTENT = "历史查询"
DESCRIPTION = "用户询问历史对话或历史行程 → 历史查询。"

from xiao_wen.memory import get_itineraries, get_preferences  # noqa: E402

# 问题关键词 → 查询方向（无 user_input 时视为综合查询，向后兼容）
_TRIP_WORDS = ("行程", "出差", "去哪", "路线", "计划", "安排", "游记")
_PREF_WORDS = ("偏好", "习惯", "常住", "记忆", "喜欢", "不吃", "口味", "住宿", "忌口")


def run(state) -> dict:
    """按问题类型回答记忆查询：行程 / 偏好 / 综合；无记录给明确空态"""
    sid = state.get("session_id", "default")
    q = (state.get("user_input") or "").strip()
    prefs = get_preferences(session_id=sid)
    its = get_itineraries(session_id=sid)

    want_trip = not q or any(w in q for w in _TRIP_WORDS)
    want_pref = not q or any(w in q for w in _PREF_WORDS)

    parts: list[str] = []
    if want_trip:
        if its:
            lines = ["🗂️ 历史行程："]
            for it in reversed(its[-5:]):  # 最多显示最近 5 条
                lines.append(
                    f"· {it.get('start_date', '?')} {it.get('from_city', '?')}→{it.get('to_city', '?')}，"
                    f"{it.get('duration_days', '?')}天：{it.get('summary', '')}"
                )
            parts.append("\n".join(lines))
        else:
            parts.append("📭 暂无历史行程记录。")
    if want_pref:
        if prefs:
            parts.append("💡 记忆偏好：" + "；".join(f"{p['category']} {p['content']}" for p in prefs))
        else:
            parts.append("💡 暂无记忆偏好。")
    return {"answer": "\n\n".join(parts)}
