"""意图评测 metrics（eval-01）：混淆矩阵 / 每意图 精确率·召回率·F1 / 错误提取。

结果输入约定（与 scripts/eval/run.py 对齐）：
    result = {
        "id", "input", "recent", "expected", "got",
        "reason", "subtasks_expected", "subtasks_got",
    }
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def confusion_matrix(results: list[dict], intents: list[str]) -> dict[str, dict[str, int]]:
    """期望意图 × 实际意图 计数表；意图集合自动并上数据中出现的（防 KeyError）。"""
    known = set(intents)
    for r in results:
        known.update((r["expected"], r["got"]))
    order = list(dict.fromkeys([*intents, *sorted(known - set(intents))]))
    m = {i: dict.fromkeys(order, 0) for i in order}
    for r in results:
        m[r["expected"]][r["got"]] += 1
    return m


def per_intent_metrics(results: list[dict], intents: list[str]) -> dict[str, dict[str, float | int]]:
    """每意图 total/ok/recall/precision/f1。

    recall = 期望为该意图的用例中分类正确的比例；
    precision = 实际预测为该意图的用例中分类正确的比例（缺分类的意图记 0）。
    """
    expected: dict[str, int] = defaultdict(int)
    got: dict[str, int] = defaultdict(int)
    ok: dict[str, int] = defaultdict(int)
    for r in results:
        exp = r["expected"]
        g = r["got"]
        expected[exp] += 1
        got[g] += 1
        if exp == g:
            ok[exp] += 1

    out: dict[str, dict[str, float | int]] = {}
    for i in intents:
        tp = ok[i]
        recall = tp / expected[i] if expected[i] else 0.0
        precision = tp / got[i] if got[i] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[i] = {
            "total": expected[i],
            "ok": tp,
            "recall": round(recall, 4),
            "precision": round(precision, 4),
            "f1": round(f1, 4),
        }
    return out


def accuracy(results: list[dict]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r["expected"] == r["got"]) / len(results)


def errors(results: list[dict]) -> list[dict]:
    """失败用例原样抽出（供 errors.jsonl 落盘与错误分析）。"""
    return [r for r in results if r["expected"] != r["got"]]


def summarize(results: list[dict], intents: list[str], threshold: float) -> dict[str, Any]:
    """一键汇总：metrics.json 的完整载荷（可 JSON 序列化，落盘即用）。"""
    acc = accuracy(results)
    errs = errors(results)
    return {
        "set": "intent",
        "total": len(results),
        "passed": len(results) - len(errs),
        "accuracy": round(acc, 4),
        "threshold": threshold,
        "pass": acc >= threshold,
        "by_intent": per_intent_metrics(results, intents),
        "confusion": confusion_matrix(results, intents),
    }
