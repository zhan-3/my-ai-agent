"""意图识别集成测试（真实 LLM，「对意图识别进行验证」）

跑法：uv run pytest -m integration
单一来源：xiao_wen.intent（system 与 graph_builder 调度图共用同一 classify）
"""

import pytest

from xiao_wen import intent as _intent

# 典型用例：从产品验证用例固化而来（含产品边界：个人休闲 → 其他）
CASES = [
    ("10月8日去北京开会4天", "行程规划"),
    ("我不吃辣，住宿喜欢安静", "偏好记录"),
    ("我上次的行程是什么", "历史查询"),
    ("出差住宿标准是什么", "知识问答"),
    ("北京今天天气怎么样", "联网查询"),
    ("这个暑假去哪里玩", "其他"),
    ("我想去三亚度假两周", "其他"),  # 产品边界：个人休闲游 → 其他
]

# 多意图拆分用例：一句话两个独立请求 → 2 条 subtasks（调度优化并行路径）
MULTI_CASES = [
    ("帮我查下出差住宿标准是什么，顺便看看北京今天天气怎么样", ["知识问答", "联网查询"]),
    ("我上次的行程是什么，还有上海明天天气怎么样", ["历史查询", "联网查询"]),
]

# 外部扩展子 Agent 用例：差旅统计由注册表动态发现（多 Agent 化核心证据）
# 默认词汇表 = discover()（六内置 + 外部 stats），无需 set_intents
EXT_CASES = [
    ("统计一下我的出差情况", "差旅统计"),
    ("我今年出差了几次", "差旅统计"),
]


@pytest.mark.integration
@pytest.mark.parametrize("text,expected", CASES)
def test_intent_classification(text, expected):
    r = _intent.classify("", text)
    assert r.intent == expected, f"{text!r} 期望 {expected}，实际 {r.intent}（{r.reason}）"
    assert r.subtasks == [], "单意图请求不应拆分出子任务"


# ---- 待补全续接（规则兑底，纯逻辑不依赖 LLM） ----


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


@pytest.mark.integration
@pytest.mark.parametrize("text,expected", MULTI_CASES)
def test_intent_splits_subtasks(text, expected):
    r = _intent.classify("", text)
    assert [s.intent for s in r.subtasks] == expected, f"{text!r} 拆分：{r.subtasks}"


@pytest.mark.integration
@pytest.mark.parametrize("text,expected", EXT_CASES)
def test_intent_discovers_external_extension(text, expected):
    """外部扩展子 Agent（差旅统计）被真实识别：注册表动态词汇表的核心验收"""
    r = _intent.classify("", text)
    assert r.intent == expected, f"{text!r} 期望 {expected}，实际 {r.intent}（{r.reason}）"
