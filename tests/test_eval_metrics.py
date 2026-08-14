"""eval-01：意图评测 metrics 纯函数单测（混淆矩阵/每意图指标/错误提取）"""

import json

from xiao_wen.eval import metrics


def _case(expected, got, input="输入", reason="", subtasks=()):
    return {
        "id": "intent-001",
        "input": input,
        "recent": "",
        "expected": expected,
        "got": got,
        "reason": reason,
        "subtasks_expected": list(subtasks),
        "subtasks_got": list(subtasks),
    }


def test_confusion_matrix_shape():
    results = [
        _case("行程规划", "行程规划"),
        _case("行程规划", "其他"),  # 错分
        _case("其他", "其他"),
    ]
    m = metrics.confusion_matrix(results, ["行程规划", "其他"])
    assert m["行程规划"]["行程规划"] == 1
    assert m["行程规划"]["其他"] == 1
    assert m["其他"]["其他"] == 1


def test_per_intent_metrics_precision_recall_f1():
    results = [
        _case("行程规划", "行程规划"),
        _case("行程规划", "其他"),  # FN
        _case("其他", "行程规划"),  # FP
        _case("其他", "其他"),
    ]
    by = metrics.per_intent_metrics(results, ["行程规划", "其他"])
    j = by["行程规划"]
    assert j["total"] == 2 and j["ok"] == 1
    assert j["recall"] == 0.5  # 2 条期望行程规划，对 1
    assert j["precision"] == 0.5  # 实际预测行程规划 2 次，对 1
    assert abs(j["f1"] - 0.5) < 1e-9


def test_accuracy_and_errors():
    results = [
        _case("行程规划", "行程规划"),
        _case("历史查询", "其他", input="我上次的行程", reason="闲聊"),
    ]
    assert metrics.accuracy(results) == 0.5
    errs = metrics.errors(results)
    assert len(errs) == 1
    assert errs[0]["input"] == "我上次的行程" and errs[0]["reason"] == "闲聊"


def test_summarize_serializable():
    results = [_case("知识问答", "知识问答")] * 2
    s = metrics.summarize(results, ["知识问答"], threshold=0.9)
    json.dumps(s)  # 必须可 JSON 序列化（落盘 metrics.json）
    assert s["total"] == 2 and s["accuracy"] == 1.0 and s["pass"] is True
    assert s["threshold"] == 0.9


def test_summarize_pass_flag_respects_threshold():
    results = [_case("知识问答", "其他")]
    s = metrics.summarize(results, ["知识问答"], threshold=0.95)
    assert s["pass"] is False
