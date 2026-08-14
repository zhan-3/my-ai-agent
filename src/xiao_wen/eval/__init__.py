"""eval 评测 harness 的可引用纯函数（规则/结构层，无 LLM）。

- metrics：规则层（意图相等/混淆矩阵）+ 结构层（check_trip_plan 行程结构校验）
- runners：批量分类 runner（classify_fn 可注入，测试不烧 LLM）
- trace：TraceRecord 采集（Recorder + run_chat_with_trace，graph/chat 插桩）
scripts/eval/run.py 只做 CLI 与落盘，不放逻辑。
"""

__all__ = [
    "accuracy",
    "check_trip_plan",
    "confusion_matrix",
    "errors",
    "per_intent_metrics",
    "summarize",
]
