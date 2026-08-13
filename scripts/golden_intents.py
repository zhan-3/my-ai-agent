#!/usr/bin/env python3
"""黄金测试集回归：真实 LLM 批量意图分类，统计准确率（第三阶段标尺）。

用法：uv run python scripts/golden_intents.py [--verbose] [--threshold 0.95]
数据：tests/data/intent_golden.jsonl（每条 {input, recent?, expected, subtasks?}）
不进 pytest（LLM 波动 + 烧 token）：作为手动回归工具与 CI integration 门禁
（阈值由实测基线留余量得出，不用 100% 避免 flaky 假红）。
"""

import argparse
import json
import sys
from pathlib import Path

from xiao_wen.intent import classify

DATA = Path(__file__).resolve().parent.parent / "tests" / "data" / "intent_golden.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--threshold", type=float, default=1.0, help="通过率下限（0-1），低于则退出码 1")
    args = ap.parse_args()

    cases = [json.loads(line) for line in DATA.read_text().splitlines() if line.strip()]
    total = len(cases)
    wrong: list[tuple[dict, str, str]] = []
    by_intent: dict[str, list[int]] = {}

    for c in cases:
        r = classify(c.get("recent", ""), c["input"])
        by_intent.setdefault(c["expected"], [0, 0])
        by_intent[c["expected"]][1] += 1
        ok = r.intent == c["expected"]
        sub_ok = True
        want_sub = c.get("subtasks")
        if want_sub is not None:
            got_sub = [s.intent for s in r.subtasks]
            sub_ok = got_sub == want_sub
        if ok and sub_ok:
            by_intent[c["expected"]][0] += 1
        else:
            wrong.append((c, r.intent, ",".join(s.intent for s in r.subtasks)))
            if args.verbose:
                print(
                    f"  ✗ {c['input'][:34]!r} → {r.intent} (期望 {c['expected']})"
                    f" | subtasks={[s.intent for s in r.subtasks]} | {r.reason[:40]}"
                )

    print(f"\n黄金测试集：{total} 条 | 通过 {total - len(wrong)} | 失败 {len(wrong)}")
    print(f"整体准确率：{(total - len(wrong)) / total:.0%}")
    for intent, (ok, n) in sorted(by_intent.items(), key=lambda x: x[1][1], reverse=True):
        print(f"  {intent}: {ok}/{n}（{ok / n:.0%}）")
    if wrong:
        print("\n失败明细：")
        for c, got, subs in wrong:
            print(
                f"  · {c['input'][:40]} | 期望 {c['expected']} | 实际 {got} | subtasks=[{subs}] | {c.get('note', '')}"
            )
    rate = (total - len(wrong)) / total
    ok = rate >= args.threshold
    print(f"通过率 {rate:.0%} vs 阈值 {args.threshold:.0%} → {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
