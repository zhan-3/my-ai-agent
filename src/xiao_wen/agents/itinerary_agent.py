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


def collect_upstream(user_input: str, session_id: str) -> dict:
    """collect-then-compose 的收集阶段（串行节点，图上只跑一次、先于 fan-out）：

    上游 = 知识库（公司差旅政策/标准，rag 纯检索）+ 历史行程参考（最近 2 条）
    + 本轮偏好（结构化提取，供行程分支生成时并入 prefs）。
    任一上游失败降级为空，不阻塞规划。
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
    prefs_turn = _extract_turn_prefs(user_input)
    return {"policy": policy, "history_ref": history_ref, "prefs_turn": prefs_turn}


def _extract_turn_prefs(user_input: str) -> str:
    """本轮偏好结构化提取：复用偏好提取器，把「本轮新陈述的偏好」拼成一行文本。

    竞态根因（多意图并行）：p_偏好记录（写库）与 p_行程规划（读偏好）并行，写读顺序不定，
    行程分支可能读不到本轮刚说的偏好。这里在串行 collect 阶段先提取一次注入上游黑板，
    行程分支生成时并入 prefs。不写库（写库仍由偏好分支负责），只用于本轮生成上下文。
    """
    from xiao_wen.agents import preference_agent

    try:
        r = preference_agent._invoke_pref_model(user_input)
    except Exception:
        return ""  # 提取失败降级为空：历史偏好仍可用，规划不阻塞
    if not r.records:
        return ""
    return "；".join(f"{rec.category}:{rec.content}" for rec in r.records)


def run(state) -> dict:
    """收尾者（collect-then-compose 的 compose 阶段）：读图级 collect 节点写入的黑板 upstream，
    委托深模块 xiao_wen.trip_planner.handle 完成规划 + 展示拼装（预算/天气/日期模糊提示）。
    上游缺失（直接调用/旧路径）→ upstream 空，槽位降级「无」，行为兼容。
    """
    from xiao_wen.trip_planner import handle

    out = handle(
        state["user_input"],
        session_id=state.get("session_id", "default"),
        recent=state.get("recent", ""),
        upstream=state.get("upstream") or {},
    )
    return {"answer": out.answer, "plan": out.plan}
