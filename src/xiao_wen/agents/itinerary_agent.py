"""内置子 Agent：行程规划（多 Agent 架构的子 Agent 实体）

元数据：INTENT / DESCRIPTION 由注册中心 AST 只读（渐进式披露，派发前零加载）。
run(state) -> dict：统一子 Agent 接口，state 含 user_input / recent。
实现收口于深模块 xiao_wen.trip_planner（ADR-0003：编排顺序是产品行为，不许改）。
"""

INTENT = "行程规划"
DESCRIPTION = (
    "用户请助理安排行程、出差计划，或询问行程安排 → 行程规划。"
    "负责生成逐日行程（交通/住宿/餐饮/预算）、常驻城市补全与缺项提示，并写回长期记忆。"
)

from xiao_wen.trip_planner import NeedsInfo, format_plan, needs_info_text  # noqa: E402
from xiao_wen.trip_planner import plan as _trip_plan  # noqa: E402


def run(state) -> dict:
    """两阶段管线（要素提取→行程生成）收口于 trip_planner.plan（ADR-0003）"""
    r = _trip_plan(state["user_input"], session_id=state.get("session_id", "default"))
    if isinstance(r, NeedsInfo):
        return {"answer": needs_info_text(r)}
    return {"answer": format_plan(r.plan)}
