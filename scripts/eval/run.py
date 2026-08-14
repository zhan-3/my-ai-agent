#!/usr/bin/env python3
"""评测 harness CLI（eval-01）：意图分类评测第一层（规则层，无 LLM judge）。

用法：uv run python scripts/eval/run.py --set intent [--threshold 0.95] [--verbose]
数据：tests/data/intent_golden.jsonl（暂不迁移；第二层 tools 集落地时进 tests/data/eval/）
产物：eval_runs/latest/{metrics.json, errors.jsonl, report.md}（含混淆矩阵）
退出码：accuracy < threshold → 1（对齐 golden_intents.py 门禁语义）。
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from xiao_wen.eval import metrics
from xiao_wen.intent import _intents, classify

ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN = ROOT / "tests" / "data" / "intent_golden.jsonl"
OUT_DIR = ROOT / "eval_runs" / "latest"


def _intent_order() -> list[str]:
    return [m["INTENT"] for m in _intents()]


def _collect(cases: list[dict], verbose: bool) -> tuple[list[dict], list[dict]]:
    """批量 classify：返回 (results, raw_failures)。results 即 metrics 输入约定。"""
    results = []
    failures = []
    for i, c in enumerate(cases):
        r = classify(c.get("recent", ""), c["input"])
        got_sub = [s.intent for s in r.subtasks]
        result = {
            "id": c.get("id", f"intent-{i:03d}"),
            "input": c["input"],
            "recent": c.get("recent", ""),
            "expected": c["expected"],
            "got": r.intent,
            "reason": r.reason,
            "subtasks_expected": c.get("subtasks", []),
            "subtasks_got": got_sub,
            "source": c.get("source", "human"),
            "note": c.get("note", ""),
        }
        results.append(result)
        if r.intent != c["expected"] or (c.get("subtasks") is not None and got_sub != c["subtasks"]):
            failures.append(result)
            if verbose:
                print(
                    f"  ✗ {c['input'][:34]!r} → {r.intent} (期望 {c['expected']})"
                    f" | subtasks={got_sub} | {r.reason[:40]}"
                )
    return results, failures


def _write_report(summary: dict, failures: list[dict]) -> Path:
    cm = summary["confusion"]
    intents = list(cm.keys())
    lines = [
        f"# 评测报告：{summary['set']}",
        "",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 样本：{summary['total']} | 通过 {summary['passed']} | 准确率 {summary['accuracy']:.0%}"
        f" | 阈值 {summary['threshold']:.0%} → {'PASS' if summary['pass'] else 'FAIL'}",
        "",
        "## 分意图指标",
        "",
        "| 意图 | 样本 | 正确 | 精确率 | 召回率 | F1 |",
        "|---|---|---|---|---|---|",
    ]
    for i, m in summary["by_intent"].items():
        lines.append(f"| {i} | {m['total']} | {m['ok']} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} |")
    lines += ["", "## 混淆矩阵（行=期望，列=实际）", ""]
    head = "| 期望 \\ 实际 | " + " | ".join(intents) + " |"
    sep = "|" + "---|" * (len(intents) + 1)
    lines += [head, sep]
    for exp in intents:
        row = " | ".join(str(cm[exp][act]) for act in intents)
        lines.append(f"| {exp} | {row} |")
    lines += ["", "## 失败明细", ""]
    if failures:
        for f in failures:
            lines.append(
                f"- `{f['id']}` {f['input'][:40]!r} 期望 {f['expected']} 实际 {f['got']}"
                f"（subtasks 期望 {f['subtasks_expected']} 实际 {f['subtasks_got']}）{f['reason'][:50]}"
            )
    else:
        lines.append("（无）")
    report = OUT_DIR / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="晓问评测 harness（第一层：意图分类）")
    ap.add_argument("--set", choices=["intent"], default="intent", help="评测集（本期仅 intent）")
    ap.add_argument("--threshold", type=float, default=1.0, help="通过率下限（0-1），低于则退出码 1")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.set != "intent":
        print(f"评测集 {args.set!r} 尚未实现（本期仅 intent）", file=sys.stderr)
        return 2

    cases = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    results, failures = _collect(cases, args.verbose)
    summary = metrics.summarize(results, _intent_order(), threshold=args.threshold)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "errors.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in failures) + ("\n" if failures else ""),
        encoding="utf-8",
    )
    report = _write_report(summary, failures)

    print(f"评测 {summary['set']}: {summary['total']} 条 | 通过 {summary['passed']} | 准确率 {summary['accuracy']:.0%}")
    print(f"通过率 {summary['accuracy']:.0%} vs 阈值 {args.threshold:.0%} → {'PASS' if summary['pass'] else 'FAIL'}")
    print(f"报告：{report}")
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
