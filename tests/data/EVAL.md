# 意图评测数据

评测数据不是天然真理。标签必须能追溯到 `CONTEXT.md`、能力矩阵或 ADR；存在多种合理路由的
样本不能作为硬门禁。

| 数据集 | 用途 | 是否门禁 |
|---|---|---|
| `intent_contract.jsonl` | 人工审阅的明确产品契约 | 按需运行，允许少量模型波动 |
| `holdout_golden.jsonl` | 已暴露的历史对抗集 | 仅在修改意图分类时诊断 |

运行方式：

```bash
uv run python scripts/golden_intents.py --set contract --threshold 0.90 --min-intent 0.75
uv run python scripts/golden_intents.py --set holdout
```

真实 LLM 结果不进入日常确定性门禁，也不等同于回答质量或泛化证明。新增契约样本必须包含稳定
`id`、唯一合理的 `expected` 和可追溯的 `basis`；内部实现选择由确定性测试覆盖。
