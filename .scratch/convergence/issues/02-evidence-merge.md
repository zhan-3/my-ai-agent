# 02 — 保留多意图汇总中的结构化证据

**Status:** ready-for-agent
**Blocked by:** None
**Type:** task
**Feature:** convergence

## 背景

`make_parallel()` 会收集 `sources`，但 `merge()` 只归并 `plan/stats/history`。多意图答案中的政策
内容因此可能失去 RAG 证据，违反领域不变量。

## What to build

- 让 `merge()` 汇总所有分支的 `sources`，按 `evidence_id` 稳定去重并保持分支顺序。
- 单意图路径行为不变；没有来源的分支返回空来源，不制造占位证据。
- `ChatResult`、同步 Web 响应和 SSE `done` 继续使用同一 `KnowledgeSource` 契约。
- 评测 trace 的 final 事件记录 sources，便于政策回答回放审计。

## 验收

- [ ] `merge()` 纯函数测试覆盖无来源、单来源、多分支重复来源。
- [ ] 真实图拓扑 + 假 LLM 测试覆盖“知识问答 + 联网查询”并断言最终 sources。
- [ ] 同步 `/api/chat` 与 SSE 都返回相同证据集合。
- [ ] 政策结论缺少证据时，既有验证护栏仍会阻止其伪装为已证实事实。
- [ ] `scripts/gate.sh` 通过。

## 不做

- 不改变检索排序、相似度阈值或知识语料。
- 不把来源文本拼接逻辑复制到 Web 或前端。

