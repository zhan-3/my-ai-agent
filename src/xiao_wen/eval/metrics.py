"""意图评测 metrics（eval-01）：混淆矩阵 / 每意图 精确率·召回率·F1 / 错误提取。

结果输入约定（与 scripts/eval/run.py 对齐）：
    result = {
        "id", "input", "recent", "expected", "got",
        "reason", "subtasks_expected", "subtasks_got",
    }
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

# ---- 结构层校验器（行程集 itinerary.jsonl 用；纯函数，可单测） ----

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DAY_FIELDS = ("date", "transport", "hotel", "activities", "notes")


def check_trip_plan(plan: dict | None, *, expected_days: int | None = None) -> list[str]:
    """结构层校验：返回问题列表（空 = 通过）。

    - plan 为 None（契约降级）→ plan 缺失
    - summary 非空、days 非空列表
    - expected_days 给定时 days 数量必须相等
    - 每 day 字段齐全（contract.TripDay 五字段）；activities 必须是 list
    - 日期必须 YYYY-MM-DD 可解析，除非 plan 标记 date_is_vague=True（模糊日期跳过格式）
    """
    problems: list[str] = []
    if plan is None:
        return ["plan 缺失（契约降级为 None）"]
    if not (plan.get("summary") or "").strip():
        problems.append("summary 为空")
    days = plan.get("days")
    if not isinstance(days, list) or not days:
        problems.append("days 为空")
        return problems
    if expected_days is not None and len(days) != expected_days:
        problems.append(f"days 数量 {len(days)} != 期望 {expected_days}")
    vague = bool(plan.get("date_is_vague"))
    for i, d in enumerate(days):
        if not isinstance(d, dict):
            problems.append(f"day[{i}] 不是对象")
            continue
        missing = [k for k in _DAY_FIELDS if k not in d]
        if missing:
            problems.append(f"day[{i}] 缺字段 {missing}")
        if not vague and not _DATE_RE.match(str(d.get("date", ""))):
            problems.append(f"day[{i}] 日期不可解析: {d.get('date')!r}")
        if not isinstance(d.get("activities"), list):
            problems.append(f"day[{i}] activities 不是列表")
    return problems


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


def _case_ok(r: dict) -> bool:
    """用例通过判定：主意图对 + subtasks 断言（样本带 subtasks 字段才断言）。
    与 runners.run_intent_set 的 failures 口径保持一致（黄金集多意图样本锁 [主导, 次要] 形状）。"""
    if r["expected"] != r["got"]:
        return False
    exp = r.get("subtasks_expected")
    return exp is None or r.get("subtasks_got") == exp


def accuracy(results: list[dict]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if _case_ok(r)) / len(results)


def errors(results: list[dict]) -> list[dict]:
    """失败用例原样抽出（供 errors.jsonl 落盘与错误分析）。"""
    return [r for r in results if not _case_ok(r)]


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
