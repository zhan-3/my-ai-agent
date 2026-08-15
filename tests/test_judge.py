"""judge 层（layer 3，LLM-as-judge）测试：rubric / 截断 / 多数票 / 独立模型接缝。

原则：judge 的 LLM 调用不烧真 token——用 override 注入假模型（返回固定评分）；
真 judge 链路验证留给 scripts/eval/run.py --with-judge 手动跑。
"""

from __future__ import annotations

import types

from xiao_wen.eval import judge


def test_rubric_has_five_dimensions():
    """D4：rubric 五条齐全（任务完成/忠实度/合规性/简洁性/得体性）"""
    names = [d for d, _ in judge.RUBRIC]
    assert names == ["任务完成", "忠实度", "合规性", "简洁性", "得体性"]


def test_rubric_task_completion_has_anchors():
    """人机一致率实测（严格 0%）后修正：任务完成定义含两个满分锚点——
    缺项场景正确索取缺项 = 满分；能力外请求说明边界+引导 = 满分"""
    task = dict(judge.RUBRIC)["任务完成"]
    assert "先索取" in task  # 缺项场景锚点
    assert "能力外" in task  # 能力外请求锚点
    assert "要素已齐全却仍只追问不生成才扣分" in task


def _sample_events() -> list[dict]:
    return [
        {"type": "input", "text": "帮我规划10月20日从上海去北京出差4天", "session_id": "j1"},
        {"type": "recent", "text": "用户: 你好"},
        {"type": "classify", "intent": "行程规划", "reason": "t", "subtasks": "[]"},
        {"type": "agent", "agent": "行程规划", "out": {"answer": "行程如下", "plan": None}},
        {"type": "final", "intent": "行程规划", "answer": "行程如下", "plan": "None"},
        {"type": "memory_write", "role": "user", "content": "x"},
    ]


def test_build_judge_input_truncates_to_key_segments():
    """截断策略：只留 input/classify/agent/final 关键段，剔除 recent/memory_write 噪音"""
    text = judge.build_judge_input(_sample_events())
    assert "帮我规划10月20日从上海去北京出差4天" in text
    assert "行程规划" in text  # classify 意图
    assert "行程如下" in text  # agent 产出 / final
    assert "memory_write" not in text
    assert "用户: 你好" not in text  # recent 噪音剔除


def _crit(**overrides: int) -> dict[str, int]:
    """构造五维全 5 的 criteria，支持覆盖（纯函数测试用）"""
    base = dict.fromkeys(judge.RUBRIC_NAMES, 5)
    base.update(overrides)
    return base


class _FakeJudgeLLM:
    """假 judge 模型：with_structured_output 后 invoke 返回固定 criteria（多数票聚合用）"""

    def __init__(self, criteria_list: list[dict[str, int]]):
        self._criteria = iter(criteria_list)

    def with_structured_output(self, *args, **kwargs):
        return self

    def invoke(self, payload):
        return types.SimpleNamespace(criteria=next(self._criteria), reasons=["理由"] * 5)


def test_majority_vote_picks_mode():
    """同用例 N 次多数票：score 众数胜出；reasons 取众数那次"""
    vs = [
        judge.JudgeVerdict(score=5, criteria=_crit(), reasons=["理由5"], verdict="PASS"),
        judge.JudgeVerdict(score=4, criteria=_crit(任务完成=3), reasons=["理由4"], verdict="PASS"),
        judge.JudgeVerdict(score=5, criteria=_crit(), reasons=["理由5"], verdict="PASS"),
    ]
    final = judge.majority_vote(vs)
    assert final.score == 5
    assert final.reasons == ["理由5"]
    assert final.criteria["任务完成"] == 5


def test_majority_vote_tie_breaks_high():
    """多数票平局：取高分（4 vs 3 → 4，宽容方向）"""
    vs = [
        judge.JudgeVerdict(score=4, verdict="PASS"),
        judge.JudgeVerdict(score=3, verdict="FAIL"),
        judge.JudgeVerdict(score=3, verdict="FAIL"),
        judge.JudgeVerdict(score=4, verdict="PASS"),
        judge.JudgeVerdict(score=3, verdict="FAIL"),
        judge.JudgeVerdict(score=4, verdict="PASS"),
    ]
    final = judge.majority_vote(vs)
    assert final.score == 4


def test_judge_once_parses_criteria(monkeypatch):
    """单次判定：criteria 透传，总分/verdict 由 aggregate 代码计算"""
    c = _crit(任务完成=4)
    monkeypatch.setattr(judge, "get_judge_llm", lambda: _FakeJudgeLLM([c]))
    v = judge.judge_once(_sample_events())
    assert v.criteria == c
    assert v.score == 5  # 4+5+5+5+5=24 → 4.8 → 半进位 5
    assert v.verdict == "PASS"
    assert v.vetoed_by is None
    assert len(v.reasons) == 5


# ---------------- aggregate（一票否决聚合，纯函数） ----------------


def test_aggregate_average_rounding():
    """全 4 → score 4 PASS；{5,5,4,4,4} → 平均 4.4 → 4 PASS"""
    v = judge.aggregate(_crit(任务完成=4, 忠实度=4, 合规性=4, 简洁性=4, 得体性=4), ["r"] * 5)
    assert (v.score, v.verdict) == (4, "PASS")
    v2 = judge.aggregate(_crit(任务完成=5, 忠实度=5, 合规性=4, 简洁性=4, 得体性=4), ["r"] * 5)
    assert (v2.score, v2.verdict) == (4, "PASS")


def test_aggregate_veto_faithfulness():
    """忠实度=1 其余全 5 → FAIL、score ≤2、vetoed_by=忠实度（编造事实一票否决）"""
    v = judge.aggregate(_crit(忠实度=1), ["r"] * 5)
    assert v.verdict == "FAIL"
    assert v.score <= 2
    assert v.vetoed_by == "忠实度"


def test_aggregate_veto_compliance():
    """合规性=2 其余全 5 → FAIL、vetoed_by=合规性"""
    v = judge.aggregate(_crit(合规性=2), ["r"] * 5)
    assert v.verdict == "FAIL"
    assert v.vetoed_by == "合规性"


def test_aggregate_veto_extreme_verbosity():
    """简洁性=1 其余全 5 → FAIL、score ≤2、vetoed_by=简洁性（机械重复式极端注水否决）"""
    v = judge.aggregate(_crit(简洁性=1), ["r"] * 5)
    assert v.verdict == "FAIL"
    assert v.score <= 2
    assert v.vetoed_by == "简洁性"


def test_aggregate_no_veto_on_moderate_verbosity():
    """简洁性=2 其余全 5 → 平均 4.4 → 4 PASS（普通啰嗦不否决，仅极端注水=1 才否决）"""
    v = judge.aggregate(_crit(简洁性=2), ["r"] * 5)
    assert (v.score, v.verdict) == (4, "PASS")
    assert v.vetoed_by is None


def test_aggregate_missing_criterion_fails():
    """只给 4 条 → score 0 FAIL（防 LLM 少给键）"""
    c = {"任务完成": 5, "忠实度": 5, "合规性": 5, "简洁性": 5}
    v = judge.aggregate(c, ["r"])
    assert v.score == 0
    assert v.verdict == "FAIL"
    assert any("缺维度" in r for r in v.reasons)


def test_is_judge_independent(monkeypatch):
    """考官独立性：EVAL_JUDGE_* 三变量齐备才算独立，任一缺失回退（与 get_judge_llm 语义一致）"""
    for var in ("EVAL_JUDGE_MODEL", "EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert judge.is_judge_independent() is False

    monkeypatch.setenv("EVAL_JUDGE_MODEL", "m")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "u")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "k")
    assert judge.is_judge_independent() is True

    monkeypatch.delenv("EVAL_JUDGE_MODEL")  # 任一缺失即回退
    assert judge.is_judge_independent() is False


def test_judge_env_used_marks_source(monkeypatch):
    """judge_env_used 文案随独立性切换（日志可追溯）"""
    for var in ("EVAL_JUDGE_MODEL", "EVAL_JUDGE_BASE_URL", "EVAL_JUDGE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert "回退" in judge.judge_env_used()
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "m")
    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "u")
    monkeypatch.setenv("EVAL_JUDGE_API_KEY", "k")
    assert "EVAL_JUDGE_*" in judge.judge_env_used()
