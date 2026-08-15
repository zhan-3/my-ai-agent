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
from xiao_wen.eval.runners import run_intent_set
from xiao_wen import memory
from xiao_wen.intent import _intents, classify

ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN = ROOT / "tests" / "data" / "intent_golden.jsonl"
MATRIX = ROOT / "tests" / "data" / "matrix_golden.jsonl"
SYNTH = ROOT / "tests" / "data" / "synthetic_golden.jsonl"
OUT_DIR = ROOT / "eval_runs" / "latest"


def _intent_order() -> list[str]:
    return [m["INTENT"] for m in _intents()]


def _collect(cases: list[dict], verbose: bool) -> tuple[list[dict], list[dict]]:
    """批量 classify：迁移到 xiao_wen.eval.runners.run_intent_set（此处保留薄包装）。"""
    return run_intent_set(cases, classify_fn=classify, verbose=verbose)


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


def _run_judge(args) -> int:
    """judge 层：黄金集样本真跑 chat（trace 落盘）→ LLM-as-judge 打分 → 报告 + 10% 人工复核样本。

    只评意图集里的行程规划类样本（judge 的核心价值在回答质量，不是意图标签）；
    样本上限 --judge-sample 控制 token；多数票 --judge-n。
    """
    from xiao_wen.eval import judge as j
    from xiao_wen.eval.trace import run_chat_with_trace

    cases = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    trip_cases = [c for c in cases if c.get("expected") == "行程规划"]
    if not trip_cases:
        print("黄金集无行程规划样本，judge 无可评", file=sys.stderr)
        return 2
    sample = trip_cases[: args.judge_sample]
    print(f"judge 层：{len(sample)} 条行程规划样本 × {args.judge_n} 次多数票（模型：{j.judge_env_used()}）")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    verdicts: list[dict] = []
    samples_path = OUT_DIR / "judge_samples.jsonl"
    with samples_path.open("w", encoding="utf-8") as sf:
        for idx, c in enumerate(sample, 1):
            text = c["input"]
            # 真跑 chat：带 recent 的样本先预热 session（黄金集上下文=真实用户场景，
            # 指代/消歧/续接样本脱离上下文会变成拒答，judge 无法评价）
            recent = c.get("recent", "")
            if recent:
                store = memory
                for line in recent.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    role, _, content = line.partition(": ")
                    if role in ("user", "assistant") and content:
                        store.add_message(role, content, session_id=f"judge_{idx}")
            _, events = run_chat_with_trace(text, session_id=f"judge_{idx}")
            v = j.judge_with_votes(events, n=args.judge_n)
            # 人工复核需要看到回答原文才能独立打分：final 事件取 answer
            reply = next((e.get("answer", "") for e in events if e.get("type") == "final"), "")
            verdicts.append(
                {
                    "id": c.get("id", idx),
                    "input": text,
                    "assistant_reply": reply,
                    "score": v.score,
                    "verdict": v.verdict,
                    "reasons": v.reasons,
                }
            )
            sf.write(json.dumps(verdicts[-1], ensure_ascii=False) + "\n")
            print(f"  [{idx}/{len(sample)}] {text[:24]!r} → {v.score} {v.verdict}")

    avg = sum(v["score"] for v in verdicts) / len(verdicts)
    passes = sum(1 for v in verdicts if v["verdict"] == "PASS")
    (OUT_DIR / "judge_report.md").write_text(
        "\n".join(
            [
                "# judge 层报告（layer 3）",
                f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
                f"- 样本：{len(verdicts)}（行程规划 × {args.judge_n} 次多数票）| 模型：{j.judge_env_used()}",
                f"- 平均分：{avg:.2f} / 5 | PASS 率：{passes}/{len(verdicts)}（{passes / len(verdicts):.0%}）",
                f"- 人工复核：前 10%（{max(1, len(verdicts) // 10)} 条）见 judge_samples.jsonl，比对人机一致率",
                "",
                "| id | 输入 | 分 | 判定 | 理由摘要 |",
                "|---|---|---|---|---|",
            ]
            + [
                f"| {v['id']} | {v['input'][:24]}… | {v['score']} | {v['verdict']} | {v['reasons'][0][:30]} |"
                for v in verdicts
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\n平均分 {avg:.2f}/5 | PASS {passes}/{len(verdicts)} | 人工复核样本：{samples_path}")
    print(f"judge 报告：{OUT_DIR / 'judge_report.md'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="晓问评测 harness（规则/结构层 + judge 层）")
    ap.add_argument(
        "--set",
        choices=["intent", "matrix", "synthetic"],
        default="intent",
        help="评测集：intent（黄金集）/ matrix（要素矩阵 243 组合）/ synthetic（LLM 合成 48 条，含人工抽检修正）",
    )
    ap.add_argument("--threshold", type=float, default=1.0, help="通过率下限（0-1），低于则退出码 1")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument(
        "--with-judge", action="store_true", help="judge 层（layer 3，烧 token）：对黄金集样本真跑 chat 链路后打分"
    )
    ap.add_argument("--judge-n", type=int, default=3, help="judge 同用例多数票次数（默认 3）")
    ap.add_argument("--judge-sample", type=int, default=8, help="judge 评测样本上限（默认 8，控制 token）")
    args = ap.parse_args()

    if args.set not in ("intent", "matrix", "synthetic"):
        print(f"评测集 {args.set!r} 尚未实现（本期仅 intent/matrix/synthetic）", file=sys.stderr)
        return 2

    if args.with_judge:
        return _run_judge(args)

    data_path = {"intent": GOLDEN, "matrix": MATRIX, "synthetic": SYNTH}[args.set]
    cases = [json.loads(line) for line in data_path.read_text().splitlines() if line.strip()]
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
