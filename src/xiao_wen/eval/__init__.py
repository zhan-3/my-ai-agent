"""eval 评测 harness 的可引用纯函数（规则层，无 LLM）。

第一层：意图分类评测。metrics 全部确定性、可单测；
scripts/eval/run.py 只做 CLI 与落盘，不放逻辑。
"""

__all__ = ["accuracy", "confusion_matrix", "errors", "per_intent_metrics", "summarize"]
