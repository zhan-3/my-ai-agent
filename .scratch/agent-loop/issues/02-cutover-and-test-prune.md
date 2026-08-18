# 02 — Web 切换与旧 Workflow 测试退役

Status: resolved

Completed after: 01

Agent Loop 通过核心验收后，让同步与 SSE Web 入口统一使用新运行时，随后删除旧主管控制流及只保护
其实现细节的测试。

## 验收

- Web 同步/SSE 使用同一 Agent 事件模型。
- 不再向前端暴露固定图节点名。
- 删除被新 Loop 行为测试覆盖的 graph/scheduler/intent-split/session 实现断言。
- 保留领域事实、RAG 证据、天气失败、票务、认证、线程隔离、Postgres 和子 Agent 契约测试。
- 删除旧入口后不存在长期双运行时或双测试套件。

## Answer（2026-08-18 完成）

- `session.py` 同步与 SSE 统一走 AgentLoop；前端事件模型收敛为 start/working/done。
- 删除 `graph_builder.py`、`intent.py`、`disambiguation.py`、`scripts/golden_intents.py` 及评测数据（intent_contract/holdout_golden/EVAL/HOLDOUT）。
- 删除旧 graph/scheduler/intent-split 测试（test_graph_builder/test_graph_contract/test_scheduler/test_intent/test_intent_split/test_disambiguation）。
- 保留领域事实、RAG 证据、天气失败、票务、认证、线程隔离、Postgres 与子 Agent 契约测试。
- 验证：前端 33 passed、lint/build 通过；工作区无 `graph_builder`/意图运行时残留引用。
