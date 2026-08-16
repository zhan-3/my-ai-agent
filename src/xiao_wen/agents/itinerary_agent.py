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
    from contextlib import suppress

    from xiao_wen import rag
    from xiao_wen.memory import get_itineraries

    policy_context = rag.PolicyContext(query=user_input, evidence=(), status="not_found")
    with suppress(Exception):
        policy_context = rag.retrieve_policy(user_input)
    policy = policy_context.text
    # 兼容旧的纯文本收集接缝：测试/旧适配器可只提供 search_texts；正式路径优先保留证据。
    if not policy:
        try:
            legacy_texts = rag.search_texts(user_input)
        except Exception:
            legacy_texts = []
        if legacy_texts:
            policy = "\n\n".join(legacy_texts)
            policy_context = rag.PolicyContext(
                query=user_input,
                evidence=tuple(
                    rag.Evidence(
                        evidence_id=f"legacy-policy-{i}",
                        source="legacy-search_texts",
                        text=text,
                        similarity=0.0,
                    )
                    for i, text in enumerate(legacy_texts)
                ),
                status="grounded",
                snapshot_id="legacy-policy",
            )
    # 主动知识：目的地城市攻略、紧急流程、绿色出行不再依赖用户另问。
    # 这里用用户原话检索，城市名会由向量检索从「去北京」等表达中识别；
    # 行程生成阶段再用提取出的目的地做一次更精确的城市检索目前由同一查询覆盖。
    guidance = {"city_tips": (), "emergency_tips": (), "green_tips": ()}
    with suppress(Exception):
        destination = _extract_destination_hint(user_input)
        if destination:
            guidance = rag.retrieve_guidance(destination)
    guidance_text = "\n\n".join(
        f"【{label} · {item.source}】\n{item.text}"
        for label, key in (("城市提示", "city_tips"), ("紧急处理", "emergency_tips"), ("绿色出行", "green_tips"))
        for item in guidance.get(key, ())
    )
    guidance_sources = tuple(dict.fromkeys(item.source for items in guidance.values() for item in items))
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
    return {
        "policy": policy,
        "policy_context": policy_context,
        "policy_evidence_ids": policy_context.evidence_ids,
        "history_ref": history_ref,
        "prefs_turn": prefs_turn,
        "guidance": guidance_text,
        "guidance_sources": guidance_sources,
    }


def _extract_destination_hint(user_input: str) -> str:
    """从行程原话提取一个轻量目的地提示，失败时返回空并交给政策检索兜底。"""
    from xiao_wen.reference_data import KNOWN_CITIES

    for marker in ("去", "到", "前往"):
        if marker in user_input:
            tail = user_input.split(marker, 1)[1]
            for city in sorted(KNOWN_CITIES, key=len, reverse=True):
                if tail.startswith(city) or city in tail[:6]:
                    return city
    return ""


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
