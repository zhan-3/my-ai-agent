"""内置子 Agent：历史查询（多 Agent 架构的子 Agent 实体）

读长期记忆（xiao_wen.memory）的历史行程，原实现随子 Agent 化拆入本模块。
"""

INTENT = "历史查询"
DESCRIPTION = "用户询问历史对话或历史行程 → 历史查询。"

from xiao_wen.memory import get_itineraries  # noqa: E402


def run(state) -> dict:
    its = get_itineraries(session_id=state.get("session_id", "default"))
    if not its:
        return {"answer": "📭 暂无历史行程记录。"}
    lines = ["🗂️ 历史行程："]
    for it in reversed(its[-5:]):  # 最多显示最近 5 条
        lines.append(
            f"· {it.get('start_date', '?')} {it.get('from_city', '?')}→{it.get('to_city', '?')}，"
            f"{it.get('duration_days', '?')}天：{it.get('summary', '')}"
        )
    return {"answer": "\n".join(lines)}
