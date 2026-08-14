"""评测 runner（票 #01）：意图集批量分类（迁移自 scripts/eval/run.py 的 _collect）。

classify_fn 可注入（测试传假分类器，不烧 LLM）；run.py 只做 CLI 与落盘。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def run_intent_set(
    cases: list[dict],
    classify_fn: Callable[..., Any],
    verbose: bool = False,
) -> tuple[list[dict], list[dict]]:
    """批量 classify：返回 (results, failures)。results 即 metrics 输入约定。

    classify_fn: (recent, user_input) -> 带 .intent/.reason/.subtasks 的对象（默认 intent.classify）。
    """
    results: list[dict] = []
    failures: list[dict] = []
    for i, c in enumerate(cases):
        r = classify_fn(c.get("recent", ""), c["input"])
        got_sub = [s.intent for s in r.subtasks]
        result: dict[str, Any] = {
            "id": c.get("id", f"intent-{i:03d}"),
            "input": c["input"],
            "recent": c.get("recent", ""),
            "expected": c["expected"],
            "got": r.intent,
            "reason": r.reason,
            "subtasks_expected": c.get("subtasks"),  # None=样本未标注（不断言子任务）
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
