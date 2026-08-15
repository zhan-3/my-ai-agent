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

from xiao_wen import memory
from xiao_wen.eval import metrics
from xiao_wen.eval.runners import run_intent_set
from xiao_wen.intent import _intents, classify

ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN = ROOT / "tests" / "data" / "intent_golden.jsonl"
MATRIX = ROOT / "tests" / "data" / "matrix_golden.jsonl"
SYNTH = ROOT / "tests" / "data" / "synthetic_golden.jsonl"
HOLDOUT = ROOT / "tests" / "data" / "holdout_golden.jsonl"
CANARIES = ROOT / "tests" / "data" / "eval" / "judge_canaries.jsonl"
OUT_DIR = ROOT / "eval_runs" / "latest"

JUDGE_FALLBACK_WARNING = (
    "⚠️  judge 回退 DEEPSEEK_*：考官=考生同模型，分数存在同源偏差（自评倾向）。\n"
    "    配置 EVAL_JUDGE_MODEL / EVAL_JUDGE_BASE_URL / EVAL_JUDGE_API_KEY 消除。"
)


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
    vote_desc = "单次判定" if args.judge_n == 1 else f"× {args.judge_n} 次多数票"
    print(f"judge 层：{len(sample)} 条行程规划样本 ×{vote_desc}（模型：{j.judge_env_used()}）")

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
                for raw_line in recent.splitlines():
                    stripped = raw_line.strip()
                    if not stripped:
                        continue
                    role, _, content = stripped.partition(": ")
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
                    "criteria": v.criteria,
                    "vetoed_by": v.vetoed_by,
                    "reasons": v.reasons,
                }
            )
            sf.write(json.dumps(verdicts[-1], ensure_ascii=False) + "\n")
            print(f"  [{idx}/{len(sample)}] {text[:24]!r} → {v.score} {v.verdict}")

    avg = sum(v["score"] for v in verdicts) / len(verdicts)
    passes = sum(1 for v in verdicts if v["verdict"] == "PASS")
    # 分维度均分：只看解析成功的样本（score>0），score=0 为解析失败不参与统计
    dim_names = [n for n, _ in j.RUBRIC]
    dim_lines = ["## 分维度均分", "", "| 维度 | 均分 | ≤2 次数 |", "|---|---|---|"]
    for n in dim_names:
        vals = [v["criteria"][n] for v in verdicts if v.get("criteria") and n in v["criteria"]]
        if vals:
            dim_lines.append(f"| {n} | {sum(vals) / len(vals):.2f} | {sum(1 for x in vals if x <= 2)} |")
        else:
            dim_lines.append(f"| {n} | — | 0 |")
    (OUT_DIR / "judge_report.md").write_text(
        "\n".join(
            [
                "# judge 层报告（layer 3）",
                f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
                f"- 样本：{len(verdicts)}（行程规划 ×{vote_desc}）| 模型：{j.judge_env_used()}",
                *([f"- {JUDGE_FALLBACK_WARNING}"] if not j.is_judge_independent() else []),
                f"- 平均分：{avg:.2f} / 5 | PASS 率：{passes}/{len(verdicts)}（{passes / len(verdicts):.0%}）",
                f"- 人工复核：前 10%（{max(1, len(verdicts) // 10)} 条）见 judge_samples.jsonl，比对人机一致率",
                "",
                "| id | 输入 | 分 | 判定 | 否决 | 理由摘要 |",
                "|---|---|---|---|---|---|",
            ]
            + [
                (
                    f"| {v['id']} | {v['input'][:24]}… | {v['score']} | {v['verdict']} | "
                    f"{v.get('vetoed_by') or '-'} | {v['reasons'][0][:30]} |"
                )
                for v in verdicts
            ]
            + [""]
            + dim_lines
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\n平均分 {avg:.2f}/5 | PASS {passes}/{len(verdicts)} | 人工复核样本：{samples_path}")
    print(f"judge 报告：{OUT_DIR / 'judge_report.md'}")
    return 0


def _run_judge_canaries(args) -> int:
    """judge 金丝雀集（区分度门禁）：已知坏样本必须 FAIL/低分，好对照必须 PASS。

    零图调用（events 手工构造），只烧 judge token。任一样本不符 → exit 1。
    """
    from xiao_wen.eval import judge as j

    cases = [json.loads(line) for line in CANARIES.read_text().splitlines() if line.strip()]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    all_ok = True
    for c in cases:
        v = j.judge_with_votes(c["events"], n=args.judge_n)
        expect = c["expect"]
        ok = v.verdict == expect
        if expect == "FAIL" and "expect_max_score" in c:
            ok = ok and v.score <= c["expect_max_score"]
        if not ok:
            all_ok = False
        rows.append(
            {
                "id": c["id"],
                "bad_type": c.get("bad_type", "对照"),
                "expect": expect,
                "score": v.score,
                "verdict": v.verdict,
                "vetoed_by": v.vetoed_by,
                "criteria": v.criteria,
                "ok": ok,
                "reasons": v.reasons,
            }
        )
        print(f"  [{c['id']}] 期望 {expect} → {v.score} {v.verdict}（否决:{v.vetoed_by or '-'}）{'✅' if ok else '❌'}")

    passed = sum(1 for r in rows if r["ok"])
    lines = [
        "# judge 金丝雀报告（区分度门禁）",
        f"- 时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- 样本：{len(rows)} | 符合预期：{passed}/{len(rows)}",
        f"- 模型：{j.judge_env_used()}",
        *([f"- {JUDGE_FALLBACK_WARNING}"] if not j.is_judge_independent() else []),
        "",
        "| id | 类型 | 期望 | 实际分 | 判定 | 否决 | 结果 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['bad_type']} | {r['expect']} | {r['score']} | {r['verdict']} | "
            f"{r['vetoed_by'] or '-'} | {'✅' if r['ok'] else '❌'} |"
        )
    lines += ["", "## 失败样本 reasons", ""]
    for r in rows:
        if not r["ok"]:
            crit = "，".join(f"{k}={v}" for k, v in r["criteria"].items()) if r["criteria"] else "（无）"
            lines.append(
                f"### {r['id']}（{r['bad_type']}，期望 {r['expect']}，"
                f"实际 {r['score']} {r['verdict']}，分维度：{crit}）"
            )
            for reason in r["reasons"]:
                lines.append(f"- {reason}")
            lines.append("")
    if all_ok:
        lines.append("（无失败样本）")

    report = OUT_DIR / "canary_report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n金丝雀 {passed}/{len(rows)} 符合预期 → {'PASS' if all_ok else 'FAIL'}")
    print(f"报告：{report}")
    return 0 if all_ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="晓问评测 harness（规则/结构层 + judge 层）")
    ap.add_argument(
        "--set",
        choices=["intent", "matrix", "synthetic", "holdout"],
        default="intent",
        help=(
            "评测集：intent（黄金集）/ matrix（要素矩阵 243 组合）/ synthetic（LLM 合成 48 条）/ "
            "holdout（防过拟合对抗集，未参与规则调参）"
        ),
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="通过率下限（0-1），低于则退出码 1；holdout 默认 0.9，其余默认 1.0",
    )
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument(
        "--with-judge", action="store_true", help="judge 层（layer 3，烧 token）：对黄金集样本真跑 chat 链路后打分"
    )
    ap.add_argument(
        "--judge-n",
        type=int,
        default=1,
        help=(
            "judge 同用例判定次数（默认 1；temp=0 下多次投票几乎恒同，仅在配置独立高方差 judge 或诊断漂移时才需要 >1）"
        ),
    )
    ap.add_argument(
        "--require-independent-judge",
        action="store_true",
        help="要求 judge 使用独立考官模型（EVAL_JUDGE_* 三变量齐备），否则 exit 2（已为默认行为，保留兼容）",
    )
    ap.add_argument(
        "--allow-judge-fallback",
        action="store_true",
        help="显式放行考官回退考生同模型（DEEPSEEK_*，仅本地调试；同源自评偏差，分数不可信）",
    )
    ap.add_argument("--judge-sample", type=int, default=8, help="judge 评测样本上限（默认 8，控制 token）")
    ap.add_argument(
        "--judge-canaries",
        action="store_true",
        help="judge 金丝雀集（已知好坏样本直接打分，不跑 chat；judge 层回归门禁，不符即 exit 1）",
    )
    args = ap.parse_args()

    if args.set not in ("intent", "matrix", "synthetic", "holdout"):
        print(f"评测集 {args.set!r} 尚未实现（本期仅 intent/matrix/synthetic/holdout）", file=sys.stderr)
        return 2

    threshold = args.threshold if args.threshold is not None else (0.9 if args.set == "holdout" else 1.0)

    if args.with_judge or args.judge_canaries:
        from xiao_wen.eval import judge as j

        if not j.is_judge_independent():
            if not args.allow_judge_fallback:
                print(
                    "错误：judge 层要求独立考官（EVAL_JUDGE_MODEL/BASE_URL/API_KEY 三变量齐全），"
                    "考官=考生同模型会产生同源自评偏差",
                    file=sys.stderr,
                )
                print("      仅本地调试确需同模型时，加 --allow-judge-fallback 显式放行。", file=sys.stderr)
                print(JUDGE_FALLBACK_WARNING, file=sys.stderr)
                return 2
            print(JUDGE_FALLBACK_WARNING, file=sys.stderr)

    if args.with_judge:
        return _run_judge(args)

    if args.judge_canaries:
        return _run_judge_canaries(args)

    data_path = {"intent": GOLDEN, "matrix": MATRIX, "synthetic": SYNTH, "holdout": HOLDOUT}[args.set]
    cases = [json.loads(line) for line in data_path.read_text().splitlines() if line.strip()]
    results, failures = _collect(cases, args.verbose)
    summary = metrics.summarize(results, _intent_order(), threshold=threshold, set_name=args.set)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "metrics.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "errors.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in failures) + ("\n" if failures else ""),
        encoding="utf-8",
    )
    report = _write_report(summary, failures)

    print(f"评测 {summary['set']}: {summary['total']} 条 | 通过 {summary['passed']} | 准确率 {summary['accuracy']:.0%}")
    print(f"通过率 {summary['accuracy']:.0%} vs 阈值 {threshold:.0%} → {'PASS' if summary['pass'] else 'FAIL'}")
    print(f"报告：{report}")
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
