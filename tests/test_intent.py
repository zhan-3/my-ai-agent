"""意图识别集成测试（真实 LLM，「对意图识别进行验证」）

跑法：uv run pytest -m integration
单一来源：xiao_wen.intent（system/scheduler 两图共用同一 classify）
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
    ("我出差去过哪些城市", "差旅统计"),
]


@pytest.mark.integration
@pytest.mark.parametrize("text,expected", CASES)
def test_intent_classification(text, expected):
    r = _intent.classify("", text)
    assert r.intent == expected, f"{text!r} 期望 {expected}，实际 {r.intent}（{r.reason}）"
    assert r.subtasks == [], "单意图请求不应拆分出子任务"


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
