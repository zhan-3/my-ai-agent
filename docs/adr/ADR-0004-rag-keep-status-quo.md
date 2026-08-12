# ADR-0004：RAG 保持现状，仅补 embedding 鲁棒性

`knowledge_qa` 每次查询重新分块读语料、并按"块数"启发式决定索引复用。评估后决定：**不重构**——语料为静态 8 份文档，本地分块为毫秒级成本，count 启发式对静态语料完全正确（块数恒定 → 始终复用索引、从不重复 embed），"内容变化检测不到"是假设性故障，不会触发。仅补两处真实鲁棒性修复（在现有 `embed_texts` 上）：`dashscope.api_key` 导入期赋值改为首次 embed 时校验（缺失则快速失败并报变量名）；embed 调用包 `with_retry`。

## Considered Options

- **KnowledgeBase 重构**（build()/query() 分离 + 惰性一次策略）：否决——价值仅为结构深化，无正确性收益，对已验收交付物不值得。
- **内容哈希 manifest**：否决——静态语料下多余；记作真实产品的演进方向。
- **维持现状 + 鲁棒性修复**（选）。

## Consequences

- 来源标注、索引复用行为、每次查询分块的行为全部不变；导入 `xiao_wen.rag` 不再要求凭据先行，embed 失败自动重试。
