"""多意图拆分兜底单测（ticket 07）：主导意图清晰但次要请求被吞（subtasks 空 + 强拆分标记）
→ 确定性切句 + 尾部子句再分类补进 subtasks。桩 LLM，不跑集成。"""

from xiao_wen import intent as _intent
from xiao_wen.intent import Intent


class _FakeChain:
    def __init__(self, fn):
        self._fn = fn

    def invoke(self, payload):
        return self._fn(payload)


def _stub_model(monkeypatch, fn):
    monkeypatch.setattr(_intent, "_intent_model", lambda: _FakeChain(fn))


# ---------------- 纯函数：切句 ----------------


def test_split_subtasks_splits_at_marker_after_separator():
    assert _intent._split_subtasks("帮我规划去武汉的行程，顺便查下武汉天气") == ["查下武汉天气"]
    assert _intent._split_subtasks("我上次的行程是什么，还有上海明天天气怎么样") == ["上海明天天气怎么样"]


def test_split_subtasks_multiple_markers_segments():
    assert _intent._split_subtasks("查天气，顺便查汇率，另外看看空气质量") == ["查汇率", "看看空气质量"]


def test_split_subtasks_no_marker():
    assert _intent._split_subtasks("帮我规划去武汉的行程") == []


def test_split_subtasks_marker_without_separator_not_split():
    """「我还有事」的还有前无子句分隔符 → 不拆（防误拆）"""
    assert _intent._split_subtasks("我还有事") == []


def test_split_subtasks_strips_trailing_punct():
    assert _intent._split_subtasks("去开会，顺便订酒店。") == ["订酒店"]


# ---------------- classify 兜底（桩 LLM，两次调用） ----------------


def test_classify_appends_missing_subtask(monkeypatch):
    """LLM 吞掉次要请求（subtasks 空）→ 兜底补上，主意图不变"""
    inputs: list[str] = []

    def invoke(payload):
        inputs.append(payload["input"])
        if len(inputs) == 1:
            return Intent(intent="行程规划", reason="要求安排出差行程", subtasks=[])
        return Intent(intent="联网查询", reason="查天气", subtasks=[])

    _stub_model(monkeypatch, invoke)
    r = _intent.classify("", "帮我规划去武汉出差的行程，顺便查下武汉天气")
    assert r.intent == "行程规划"
    assert [(s.intent, s.text) for s in r.subtasks] == [
        ("行程规划", "帮我规划去武汉出差的行程，顺便查下武汉天气"),  # 归一化：主导前置（text=完整输入）
        ("联网查询", "查下武汉天气"),
    ]


def test_classify_prepends_missing_primary(monkeypatch):
    """LLM 只把次要放进 subtasks、漏掉主导（黄金集失败模式）→ 归一化前置主导"""
    inputs: list[str] = []

    def invoke(payload):
        inputs.append(payload["input"])
        if len(inputs) == 1:
            sub = _intent.SubTask(intent="偏好记录", text="记一下我现在常住深圳")
            return Intent(intent="历史查询", reason="查行程", subtasks=[sub])
        return Intent(intent="历史查询", reason="查行程", subtasks=[])

    _stub_model(monkeypatch, invoke)
    r = _intent.classify("", "我上次的行程是什么，顺便记一下我现在常住深圳")
    assert [s.intent for s in r.subtasks] == ["历史查询", "偏好记录"]
    assert r.subtasks[0].text == "我上次的行程是什么，顺便记一下我现在常住深圳"


def test_classify_skips_subtask_same_as_main(monkeypatch):
    """子句归到与主导意图相同 → 跳过（已由主导覆盖，防重复）"""
    inputs: list[str] = []

    def invoke(payload):
        inputs.append(payload["input"])
        if len(inputs) == 1:
            return Intent(intent="行程规划", reason="规划", subtasks=[])
        return Intent(intent="行程规划", reason="还是规划", subtasks=[])

    _stub_model(monkeypatch, invoke)
    r = _intent.classify("", "帮我规划去武汉的行程，顺便把行程再细化一下")
    assert r.subtasks == []


def test_classify_skips_subtask_other(monkeypatch):
    """子句归「其他」→ 跳过（垃圾子任务不进并行）"""
    inputs: list[str] = []

    def invoke(payload):
        inputs.append(payload["input"])
        if len(inputs) == 1:
            return Intent(intent="历史查询", reason="查行程", subtasks=[])
        return Intent(intent="其他", reason="闲聊", subtasks=[])

    _stub_model(monkeypatch, invoke)
    r = _intent.classify("", "我上次的行程是什么，顺便问一下")
    assert r.subtasks == []


def test_classify_llm_subtasks_present_no_fallback(monkeypatch):
    """LLM 已正确拆分 → 兜底不触发（不多花调用）"""
    calls = {"n": 0}

    def invoke(payload):
        calls["n"] += 1
        return Intent(intent="历史查询", reason="拆", subtasks=[])

    _stub_model(monkeypatch, invoke)
    r = _intent.classify("", "我上次的行程是什么")
    assert r.subtasks == [] and calls["n"] == 1
