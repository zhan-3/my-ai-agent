"""judge 金丝雀集（区分度门禁）测试。

- 无 LLM 部分：数据可加载、schema 齐全、坏类型五类覆盖、好对照 ≥4。
- integration 部分：真 judge 模型实跑全部金丝雀，断言全部符合预期。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CANARIES = Path(__file__).resolve().parent / "data" / "eval" / "judge_canaries.jsonl"

BAD_TYPES = {"fabrication", "forced_generation", "off_task", "verbosity", "leisure_not_rejected"}


def _load() -> list[dict]:
    return [json.loads(line) for line in CANARIES.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_canaries_loadable_and_schema_complete():
    cases = _load()
    assert len(cases) >= 14, "金丝雀总数应 ≥14（≥10 坏 + ≥4 好）"
    for c in cases:
        assert {"id", "bad_type", "expect", "events"} <= set(c), f"{c.get('id')} 缺字段"
        assert c["expect"] in ("PASS", "FAIL"), f"{c['id']} expect 非法"
        types = [e.get("type") for e in c["events"]]
        assert "input" in types and "final" in types, f"{c['id']} events 缺 input/final"
        if c["expect"] == "FAIL" and "expect_max_score" in c:
            assert 1 <= c["expect_max_score"] <= 5


def test_canaries_cover_all_bad_types():
    bad = {c["bad_type"] for c in _load() if c["expect"] == "FAIL"}
    assert bad >= BAD_TYPES, f"坏类型缺覆盖：{BAD_TYPES - bad}"


def test_canaries_have_enough_good_controls():
    good = [c for c in _load() if c["expect"] == "PASS"]
    assert len(good) >= 4, "好对照应 ≥4 条（防 judge 变「见谁都 FAIL」）"


@pytest.mark.integration
def test_canaries_all_pass_under_real_judge():
    """真 judge 模型实跑：坏样本必须 FAIL（有 max 时 score 也达标），好对照必须 PASS。"""
    from xiao_wen.eval import judge as j

    failures: list[str] = []
    for c in _load():
        v = j.judge_with_votes(c["events"])
        ok = v.verdict == c["expect"]
        if c["expect"] == "FAIL" and "expect_max_score" in c:
            ok = ok and v.score <= c["expect_max_score"]
        if not ok:
            reasons = " | ".join(v.reasons[:2])
            failures.append(
                f"{c['id']} ({c['bad_type']}) 期望 {c['expect']} 实际 "
                f"{v.score}/{v.verdict}（否决:{v.vetoed_by or '-'}）→ {reasons}"
            )
    assert not failures, "金丝雀被放过/误伤：\n" + "\n".join(failures)
