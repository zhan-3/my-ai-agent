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


def collect_upstream(user_input: str, session_id: str, recent: str = "") -> dict:
    """collect-then-compose 的收集阶段（串行节点，图上只跑一次、先于 fan-out）：

    上游 = 知识库（公司差旅政策/标准，rag 纯检索）+ 历史行程参考（最近 2 条）
    + 本轮偏好（结构化提取，供行程分支生成时并入 prefs）。
    任一上游失败降级为空，不阻塞规划。
    """
    from contextlib import suppress

    from xiao_wen import rag
    from xiao_wen.memory import get_itineraries

    cities = _extract_city_hints(user_input, recent)
    policy_query = (
        f"{user_input} {' '.join(cities)} 公司差旅政策 住宿标准 交通标准 报销标准 审批要求"
        if cities
        else f"{user_input} 公司差旅政策 住宿标准 交通标准 报销标准 审批要求"
    )
    policy_context = rag.retrieve_policy(policy_query)
    policy = policy_context.text
    # 主动知识：出发/目的城市攻略、紧急流程、绿色出行不再依赖用户另问。
    # 两个城市都取证：出发城市影响机场/车站和天气衔接，目的城市影响住宿、当地交通和安全。
    guidance: dict[str, tuple[rag.Evidence, ...]] = {
        "city_tips": (),
        "emergency_tips": (),
        "green_tips": (),
    }
    with suppress(Exception):
        cities = _extract_city_hints(user_input, recent)
        if cities:
            results = [rag.retrieve_guidance(city) for city in cities]
            guidance = {
                key: tuple(item for result in results for item in result.get(key, ()) if isinstance(item, rag.Evidence))
                for key in guidance
            }
            # 主动知识是注意事项，不让它挤满生成上下文：城市各取一段，其他类别各取一段。
            guidance["city_tips"] = guidance["city_tips"][:2]
            guidance["emergency_tips"] = guidance["emergency_tips"][:1]
            guidance["green_tips"] = guidance["green_tips"][:1]
    guidance_text = "\n\n".join(
        f"【{label} · {item.source}】\n{item.text}"
        for label, key in (("城市提示", "city_tips"), ("紧急处理", "emergency_tips"), ("绿色出行", "green_tips"))
        for item in guidance.get(key, ())
    )
    guidance_sources = tuple(dict.fromkeys(item.source for items in guidance.values() for item in items))
    sources = [item.__dict__ for item in policy_context.evidence]
    sources.extend(item.__dict__ for item in guidance.get("city_tips", ()))
    sources.extend(item.__dict__ for item in guidance.get("emergency_tips", ()))
    sources.extend(item.__dict__ for item in guidance.get("green_tips", ()))
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
        "policy_status": policy_context.status,
        "policy_evidence_ids": policy_context.evidence_ids,
        "history_ref": history_ref,
        "prefs_turn": prefs_turn,
        "guidance": guidance_text,
        "guidance_sources": guidance_sources,
        "sources": sources,
    }


def _extract_city_hints(user_input: str, recent: str = "") -> tuple[str, ...]:
    """提取本轮/最近对话中的出发和目的城市，保持出现顺序并去重。"""
    from xiao_wen.reference_data import KNOWN_CITIES

    found: list[str] = []
    for text in (user_input, recent):
        for city in sorted(KNOWN_CITIES, key=len, reverse=True):
            if city in text and city not in found:
                found.append(city)
    return tuple(found[:2])


def _extract_destination_hint(user_input: str, recent: str = "") -> str:
    """从本轮和最近对话提取目的地，不把常驻城市误当作目的地。"""
    from xiao_wen.reference_data import KNOWN_CITIES

    for text in (user_input, recent):
        for marker in ("去", "到", "前往"):
            if marker in text:
                tail = text.split(marker, 1)[1]
                for city in sorted(KNOWN_CITIES, key=len, reverse=True):
                    if tail.startswith(city) or city in tail[:6]:
                        return city
        candidate = text.strip(" 。，、！？!?\n")
        if candidate in KNOWN_CITIES:
            return candidate
        if text is recent:
            for raw_line in text.splitlines():
                line = raw_line.strip(" 。，、！？!?\n")
                for city in sorted(KNOWN_CITIES, key=len, reverse=True):
                    if city in line and len(line) <= 12:
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
    from xiao_wen.dialogue import focused_recent
    from xiao_wen.trip_planner import handle

    active_task = state.get("active_task")
    recent = focused_recent(active_task, state.get("recent", ""))
    out = handle(
        state["user_input"],
        session_id=state.get("user_id", state.get("session_id", "default")),
        recent=recent,
        upstream=state.get("upstream") or {},
        task_context=(active_task or {}).get("resume_context", ""),
    )
    return {
        "answer": out.answer,
        "plan": out.plan,
        "task_update": out.task_update,
        "policy_status": state.get("upstream", {}).get("policy_status"),
        "sources": state.get("upstream", {}).get("sources", []),
    }
