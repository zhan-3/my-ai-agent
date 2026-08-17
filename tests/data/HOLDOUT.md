# 意图历史对抗集

`holdout_golden.jsonl` 是已暴露的历史对抗集，只用于修改 `src/xiao_wen/intent.py` 时诊断回归；
它不是盲测集，也不进入日常门禁。

```bash
uv run python scripts/golden_intents.py --set holdout
```

报告通过数、总数和失败样本。修复失败时优先调整通用分类行为，不为单条样本继续堆叠词表。
