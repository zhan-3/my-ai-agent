# 02 — Web 切换与旧 Workflow 测试退役

Status: needs-triage

Blocked by: 01

Agent Loop 通过核心验收后，让同步与 SSE Web 入口统一使用新运行时，随后删除旧主管控制流及只保护
其实现细节的测试。

## 验收

- Web 同步/SSE 使用同一 Agent 事件模型。
- 不再向前端暴露固定图节点名。
- 删除被新 Loop 行为测试覆盖的 graph/scheduler/intent-split/session 实现断言。
- 保留领域事实、RAG 证据、天气失败、票务、认证、线程隔离、Postgres 和子 Agent 契约测试。
- 删除旧入口后不存在长期双运行时或双测试套件。
