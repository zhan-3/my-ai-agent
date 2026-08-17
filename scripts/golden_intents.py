#!/usr/bin/env python3
"""意图分类的按需真实模型检查。

默认运行人工审阅契约；`--set holdout` 运行历史对抗集。两者都不进入日常门禁。
"""

import argparse
import json
import sys
from pathlib import Path

from xiao_wen.intent import classify

DATA_DIR = Path(__file__).resolve().parent.parent / "tests" / "data"
DATASETS = {
    "contract": DATA_DIR / "intent_contract.jsonl",
    "holdout": DATA_DIR / "holdout_golden.jsonl",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=DATASETS, default="contract")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--threshold", type=float, default=1.0, help="通过率下限（0-1），低于则退出码 1")
    ap.add_argument(
        "--min-intent",
        type=float,
        default=0.0,
        help="任一意图通过率下限（0-1），防整体均值掩盖弱意图",
    )
    args = ap.parse_args()

    cases = [json.loads(line) for line in DATASETS[args.set].read_text().splitlines() if line.strip()]
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

    print(f"\n意图 {args.set} 集：{total} 条 | 通过 {total - len(wrong)} | 失败 {len(wrong)}")
    print(f"整体准确率：{(total - len(wrong)) / total:.0%}")
    weak_intents: list[tuple[str, int, int]] = []
    for intent, (ok_count, count) in sorted(by_intent.items(), key=lambda x: x[1][1], reverse=True):
        rate = ok_count / count
        print(f"  {intent}: {ok_count}/{count}（{rate:.0%}）")
        if rate < args.min_intent:
            weak_intents.append((intent, ok_count, count))
    if wrong:
        print("\n失败明细：")
        for c, got, subs in wrong:
            print(
                f"  · {c['input'][:40]} | 期望 {c['expected']} | 实际 {got} | subtasks=[{subs}] | {c.get('note', '')}"
            )
    rate = (total - len(wrong)) / total
    overall_ok = rate >= args.threshold
    intent_ok = not weak_intents
    if weak_intents:
        detail = "，".join(f"{intent}={ok_count}/{count}" for intent, ok_count, count in weak_intents)
        print(f"分意图下限 {args.min_intent:.0%} 未满足：{detail}")
    passed = overall_ok and intent_ok
    print(f"整体 {rate:.0%} vs {args.threshold:.0%}，分意图下限 {args.min_intent:.0%} → {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
