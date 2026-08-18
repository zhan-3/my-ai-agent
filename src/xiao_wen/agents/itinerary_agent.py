"""内置子 Agent：行程规划（多 Agent 架构的子 Agent 实体）

元数据：INTENT / DESCRIPTION 由注册中心 AST 只读（渐进式披露，派发前零加载）。
run(state) -> dict：统一子 Agent 接口，state 含 user_input / recent。
实现收口于深模块 xiao_wen.trip_planner（ADR-0003：编排顺序是产品行为，不许改）。
"""

INTENT = "行程规划"
DESCRIPTION = (
    "用户请助理安排行程、出差计划或行程细节（帮我规划/安排/排/订/物色落脚点/弄个安排，"
    "含口语化表达），或询问行程安排 → 行程规划。"
    "负责生成逐日行程（交通/住宿/餐饮/预算）、常驻城市补全与缺项提示，并写回长期记忆。"
    "公司团建、个人旅游/度假（如五一去三亚玩）不属于企业差旅，不归这里。"
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
    policy_context = rag.retrieve_trip_policy(policy_query)
    # 进 LLM 的约束只含 01 差旅标准；02 报销只取 fact 供返程提醒（原文不进生成上下文）。
    policy = "\n\n".join(e.text for e in policy_context.evidence if e.source == "01_travel_standards")
    # 主动知识：只按目的地/出发地注入城市贴士（07）。应急（05）走天气风险触发或用户问答，
    # 绿色（08）靠 01 环保章节与用户问答，均不随行程规划无条件注入。
    guidance: dict[str, tuple[rag.Evidence, ...]] = {"city_tips": ()}
    with suppress(Exception):
        cities = _extract_city_hints(user_input, recent)
        if cities:
            results = [rag.retrieve_guidance(city) for city in cities]
            guidance["city_tips"] = tuple(
                item for result in results for item in result if isinstance(item, rag.Evidence)
            )[:2]
    guidance_text = "\n\n".join(f"【城市提示 · {item.source}】\n{item.text}" for item in guidance.get("city_tips", ()))
    guidance_sources = tuple(dict.fromkeys(item.source for item in guidance.get("city_tips", ())))
    sources = [item.__dict__ for item in policy_context.evidence]
    sources.extend(item.__dict__ for item in guidance.get("city_tips", ()))
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
    """提取本轮/最近对话中的出发和目的城市，保持出现顺序并去重。

    白名单（KNOWN_CITIES）最长匹配优先；再补提白名单之外的出发城市（「从X出发」，
    如临沂）与常驻城市声明，保证城市攻略/应急/绿色知识也能注入。
    """
    import re

    from xiao_wen.reference_data import KNOWN_CITIES
    from xiao_wen.trip_planner import _detect_home_city, _looks_like_city_name

    _LOCATION_WORDS = ("家里", "这边", "那儿", "那里", "当地", "公司", "单位", "酒店", "机场", "车站")
    found: list[str] = []
    for text in (user_input, recent):
        for city in sorted(KNOWN_CITIES, key=len, reverse=True):
            if city in text and city not in found:
                found.append(city)
        # 非白名单出发城市：从X出发 / 从X走 / 从X过来（X 为 2-4 字城市名，如临沂）
        for m in re.finditer(r"从(.{2,4}?)(?:出发|走|过来)", text):
            city = m.group(1)
            if city not in _LOCATION_WORDS and _looks_like_city_name(city) and city not in found:
                found.append(city)
        home = _detect_home_city(text)
        if home and home not in found:
            found.append(home)
    return tuple(found[:3])


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
    owner_id = state.get("user_id", state.get("session_id", "default"))
    upstream = state.get("upstream")
    if upstream is None:
        upstream = collect_upstream(state["user_input"], owner_id, recent)
    out = handle(
        state["user_input"],
        session_id=owner_id,
        recent=recent,
        upstream=upstream,
        task_context=(active_task or {}).get("resume_context", ""),
        cancelled=state.get("_cancelled"),
        defer_write=bool(state.get("_defer_writes")),
    )
    return {
        "answer": out.answer,
        "plan": out.plan,
        "task_update": out.task_update,
        "policy_status": upstream.get("policy_status"),
        "sources": upstream.get("sources", []),
        "memory_writes": out.memory_writes,
    }
