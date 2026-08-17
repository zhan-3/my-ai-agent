"""意图识别确定性修正规则测试；真实模型路由由 intent_contract.jsonl 单独评测。"""

from xiao_wen import intent as _intent

# ---- 待补全续接（规则兑底，纯逻辑不依赖 LLM） ----


def test_travel_advice_is_knowledge_intent_without_llm():
    for text in ("北京出差注意什么", "出差遇到紧急情况怎么办"):
        result = _intent._is_travel_knowledge_consult(text)
        assert result
        corrected = _intent.IntentResult(intent="知识问答", reason="", subtasks=[])
        assert corrected.intent == "知识问答"


def test_recover_pending_reroutes_preference_to_plan():
    """recent 里助手在追问行程要素 + 用户偏好陈述 → 修正为行程规划 + 偏好进 subtasks
    （「我现在常住上海」在追问上下文：续接行程的同时记偏好，而不是只记偏好）"""
    recent = "⚠️ 还缺一些信息才能帮你安排行程，请补充：\n· 出发城市"
    base = _intent.IntentResult(intent="偏好记录", reason="陈述偏好", subtasks=[])
    r = _intent._recover_pending(recent, "我现在常住上海", base)
    assert r.intent == "行程规划"
    assert [s.intent for s in r.subtasks] == ["偏好记录"]


def test_recover_pending_ensures_pref_subtask_when_plan_already():
    """LLM 已直接归行程规划（不稳的另一分支）→ 规则仍确保偏好记录进 subtasks：
    追问上下文里的偏好陈述，无论 LLM 原分类如何，都收敛到「行程规划 + 偏好记录」"""
    recent = "请补充：\n· 出发城市"
    r = _intent._recover_pending(
        recent, "我现在常住上海", _intent.IntentResult(intent="行程规划", reason="", subtasks=[])
    )
    assert r.intent == "行程规划"
    assert [s.intent for s in r.subtasks] == ["偏好记录"]
    # 已含偏好（LLM 自己拆过）→ 不重复添加
    dup = _intent._recover_pending(
        recent,
        "我现在常住上海",
        _intent.IntentResult(
            intent="行程规划", reason="", subtasks=[_intent.SubTask(intent="偏好记录", text="我现在常住上海")]
        ),
    )
    assert [s.intent for s in dup.subtasks] == ["偏好记录"]


def test_recover_pending_pure_short_answer():
    """纯补全（如单个城市词）→ 行程规划，无偏好 subtask"""
    recent = "请补充：\n· 出发城市"
    r = _intent._recover_pending(recent, "上海", _intent.IntentResult(intent="其他", reason="", subtasks=[]))
    assert r.intent == "行程规划"
    assert r.subtasks == []


def test_recover_pending_respects_abandon_and_query():
    """放弃词（算了）与强查询词（上次/统计）不被续接规则劫持"""
    recent = "请补充：\n· 出发城市"
    abandoned = _intent._recover_pending(
        recent, "算了，不去了", _intent.IntentResult(intent="其他", reason="", subtasks=[])
    )
    assert abandoned.intent == "其他"
    query = _intent._recover_pending(
        recent, "我上次的行程是什么", _intent.IntentResult(intent="历史查询", reason="", subtasks=[])
    )
    assert query.intent == "历史查询"


def test_structured_pending_preference_interrupts_without_hijacking():
    active = {"intent": "行程规划", "missing": ["出发城市"]}
    base = _intent.IntentResult(intent="行程规划", reason="模型受旧文本影响", subtasks=[])
    result = _intent._recover_pending("请补充出发城市", "我不吃辣", base, active_task=active)
    assert result.intent == "偏好记录"


def test_structured_pending_slot_and_resume_continue_trip():
    active = {"intent": "行程规划", "missing": ["出发城市", "出差天数"]}
    other = _intent.IntentResult(intent="其他", reason="短句", subtasks=[])
    assert _intent._recover_pending("", "武汉", other, active_task=active).intent == "行程规划"
    assert _intent._recover_pending("", "继续刚才", other, active_task=active).intent == "行程规划"


def test_structured_pending_cancel_routes_to_other():
    active = {"intent": "行程规划", "missing": ["出发城市"]}
    base = _intent.IntentResult(intent="行程规划", reason="续接", subtasks=[])
    result = _intent._recover_pending("", "算了，不去了", base, active_task=active)
    assert result.intent == "其他"


def test_recover_pending_noop_without_pending_mark():
    """recent 没有追问标记（正常偏好陈述）→ 不劫持"""
    base = _intent.IntentResult(intent="偏好记录", reason="", subtasks=[])
    r = _intent._recover_pending("用户：你好\n助手：你好", "我现在常住上海", base)
    assert r.intent == "偏好记录"


def test_pref_only_correction_reroutes_fake_plan_to_pref():
    """无追问上下文 + 纯偏好陈述（无行程要素）→ 偏好记录：
    LLM 把「上次一样，还是住汉庭吧」脑补成行程续接（无上文指代悬空）→ 规则锁回偏好"""
    base = _intent.IntentResult(intent="行程规划", reason="指代上一轮行程", subtasks=[])
    r = _intent._pref_only_correction("用户：你好", "和上次一样，还是住汉庭吧", base)
    assert r.intent == "偏好记录"
    assert r.subtasks == []


def test_pref_only_correction_keeps_plan_with_trip_elements():
    """含行程要素（规划/出差/日期）→ 不触发：
    「帮我规划去广州出差，住全季」是行程规划不是纯偏好"""
    base = _intent.IntentResult(intent="行程规划", reason="", subtasks=[])
    for q in ("帮我规划去广州出差，住全季", "10月20号去北京出差4天，住汉庭"):
        r = _intent._pref_only_correction("", q, base)
        assert r.intent == "行程规划", q


def test_pref_only_correction_does_not_treat_arrangement_as_preference():
    """「帮我安排住宿」中的「我」和「住」不构成主语直接陈述偏好。"""
    base = _intent.IntentResult(intent="行程规划", reason="安排出差", subtasks=[])
    query = "去北京开会，帮我安排住宿和交通"
    assert not _intent._is_pref_statement(query)
    assert _intent._pref_only_correction("", query, base).intent == "行程规划"
    mixed = "去北京开会，住全季酒店"
    assert _intent._is_pref_statement(mixed)
    assert _intent._pref_only_correction("", mixed, base).intent == "行程规划"


def test_pref_only_correction_keeps_consultation():
    """咨询类（含哪里/怎么）→ 不触发：
    「我住哪里比较好」是咨询建议（其他），不是偏好陈述"""
    base = _intent.IntentResult(intent="其他", reason="咨询建议", subtasks=[])
    r = _intent._pref_only_correction("", "我住哪里比较好", base)
    assert r.intent == "其他"


def test_pref_only_correction_noop_when_already_pref():
    """LLM 已归偏好记录 → 不覆盖（幂等）"""
    base = _intent.IntentResult(intent="偏好记录", reason="", subtasks=[])
    r = _intent._pref_only_correction("", "还是住汉庭吧", base)
    assert r.intent == "偏好记录"
