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


class _FakeJudgeLLM:
    """假 judge 模型：with_structured_output 后 invoke 返回固定评分（多数票聚合用）"""

    def __init__(self, scores: list[int]):
        self._scores = iter(scores)

    def with_structured_output(self, *args, **kwargs):
        return self

    def invoke(self, payload):
        score = next(self._scores)
        return types.SimpleNamespace(
            score=score,
            reasons=[f"理由{score}"],
            verdict="PASS" if score >= 4 else "FAIL",
        )


def test_majority_vote_picks_mode(monkeypatch):
    """同用例 N 次多数票：score 众数胜出；reasons 取众数那次"""
    monkeypatch.setattr(judge, "get_judge_llm", lambda: _FakeJudgeLLM([5, 4, 5]))
    verdicts = [judge.judge_once(_sample_events()) for _ in range(3)]
    final = judge.majority_vote(verdicts)
    assert final.score == 5
    assert final.reasons == ["理由5"]


def test_majority_vote_tie_breaks_high(monkeypatch):
    """多数票平局：取高分（4 vs 3 → 4，宽容方向）"""
    monkeypatch.setattr(judge, "get_judge_llm", lambda: _FakeJudgeLLM([4, 3, 3, 4, 3, 4]))
    verdicts = [judge.judge_once(_sample_events()) for _ in range(6)]
    final = judge.majority_vote(verdicts)
    assert final.score == 4


def test_judge_once_parses_verdict(monkeypatch):
    """单次判定：score/reasons/verdict 解析齐全"""
    monkeypatch.setattr(judge, "get_judge_llm", lambda: _FakeJudgeLLM([4]))
    v = judge.judge_once(_sample_events())
    assert v.score == 4
    assert v.verdict == "PASS"
    assert "理由4" in v.reasons
