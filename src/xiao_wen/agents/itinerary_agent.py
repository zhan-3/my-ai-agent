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

from contextlib import suppress  # noqa: E402

from xiao_wen.trip_planner import NeedsInfo, format_budget, format_plan, needs_info_text  # noqa: E402
from xiao_wen.trip_planner import plan as _trip_plan  # noqa: E402
from xiao_wen.web import get_weather  # noqa: E402


def collect_upstream(user_input: str, session_id: str) -> dict:
    """collect-then-compose 的收集阶段（确定性、零 LLM）：

    上游 = 知识库（公司差旅政策/标准，rag 纯检索）+ 历史行程参考（最近 2 条）
    + 用户偏好（trip_planner 内已有）。任一上游失败降级为空，不阻塞规划。
    """
    from xiao_wen import rag
    from xiao_wen.memory import get_itineraries

    policy = ""
    try:
        policy = "\n\n".join(rag.search_texts(user_input))  # rag 内部也已降级为 []
    except Exception:
        policy = ""  # 索引/网络异常：政策上下文降级为空，规划不阻塞
    history_ref = ""
    try:
        its = get_itineraries(session_id=session_id)
        history_ref = "\n".join(
            f"- {it.get('start_date', '')} {it.get('from_city', '')}→{it.get('to_city', '')}"
            f" {it.get('duration_days', '')}天：{it.get('summary', '')}"
            for it in its[-2:]
        )
    except Exception:
        history_ref = ""  # 记忆后端异常：历史参考降级为空
    return {"policy": policy, "history_ref": history_ref}


def run(state) -> dict:
    """收尾者（collect-then-compose 的 compose 阶段）：读图级 collect 节点写入的黑板 upstream，
    综合生成行程。上游缺失（直接调用/旧路径）→ upstream 空，槽位降级「无」，行为兼容。

    两阶段管线（要素提取→行程生成）收口于 trip_planner.plan（ADR-0003）；
    生成成功后附加目的地天气提醒。
    """
    upstream = state.get("upstream") or {}
    r = _trip_plan(
        state["user_input"],
        session_id=state.get("session_id", "default"),
        recent=state.get("recent", ""),
        upstream=upstream,
    )
    if isinstance(r, NeedsInfo):
        return {"answer": needs_info_text(r), "plan": None}
    answer = format_plan(r.plan)
    req = r.request
    if req and req.date_is_vague:
        # 日期模糊（如只说了「下周」）：明示按推断日期安排，给用户确认/调整机会（业界标准：先给方案、可改）
        answer += (
            f"\n\n📅 你只说了出发时间的大致范围，我按 {req.start_date} 开始安排——"
            "如果实际日期不同，告诉我具体日期，我重新排。"
        )
    if req:
        # 预算块：确定性真实票价/标准价（LLM 不编数字，避免幻觉）
        with suppress(Exception):
            answer += f"\n\n{format_budget(req)}"
    if req and req.to_city not in ("待定", "未知", "") and req.start_date not in ("待定", ""):
        with suppress(Exception):  # 天气是锦上添花：查不到（超 7 天/网络异常）不影响行程主答案
            answer += f"\n\n🌤️ 目的地天气提醒：{get_weather.invoke({'city': req.to_city, 'date': req.start_date})}"
    # 结构化 plan（slice 1）：展示层数据驱动。预算/天气刻意留在文本，前端从文本解析附加块
    plan = r.plan.model_dump()
    plan["date_is_vague"] = bool(req and req.date_is_vague)
    return {"answer": answer, "plan": plan}
