# 06 — 统一依赖结果、readiness 与 HTTP 故障语义

**Status:** ready-for-agent
**Blocked by:** 01, 04
**Type:** task
**Feature:** convergence

## 背景

政策无命中、Embedding 故障、Chroma 损坏和网络错误在部分路径中都会变成空值；另一些路径则
抛异常。`/healthz` 无论关键依赖是否可用都返回 200，调用方缺少稳定故障语义。

## What to build

- 深化现有 `PolicyContext`，让状态至少覆盖 `grounded/not_found/unavailable/stale/ambiguous`。
- `PolicyProvider.retrieve()` 在内部分类外部 adapter 异常，不让调用方解析异常文本或空列表。
- 行程规划在 unavailable 时显式说明政策服务不可用，并继续禁止无证据政策结论。
- 知识问答、行程上游和评测 trace 使用同一状态语义。
- 拆分 `/livez` 与 `/readyz`：前者只判断进程存活，后者检查 Postgres、必要配置、RAG 文档和静态资源。
- readiness 不执行写入；未就绪返回非 2xx。系统故障与正常业务拒答使用不同 HTTP/SSE 结果。

## 接口约束

- Web 层只映射领域结果到 HTTP，不判断 Chroma、Embedding 或 psycopg 异常类型。
- 外部依赖的生产 adapter 与测试 adapter 位于内部 seam，结果类型是调用方唯一测试面。

## 验收

- [ ] not_found 与 unavailable 的单元和 Web 契约测试均覆盖。
- [ ] Postgres、RAG 文档或前端产物缺失时 `/readyz` 返回非 2xx。
- [ ] `/livez` 不调用 LLM、Embedding 或执行数据库写入。
- [ ] 行程在政策不可用时不生成无证据政策数字。
- [ ] SSE 系统故障事件与正常 done 事件可稳定区分。
- [ ] `scripts/gate.sh` 通过。

## 不做

- 不建设指标、追踪或告警平台。
- 不改变天气失败必须显式呈现的现有规则。

