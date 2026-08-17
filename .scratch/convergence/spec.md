# 收敛迭代：交付闭环与产品事实一致性

Status: ready-for-agent
Type: spec
Feature: convergence

## 目标

暂停新增产品能力，把当前系统收敛为**单实例、低并发、可部署的内部试点**。迭代完成时，
代码行为、领域约束、自动化测试、容器产物和文档描述必须一致。

## 成功标准

- 生产镜像包含 React 构建产物和 RAG 文档，可从空运行时状态启动。
- `.env` 优先级、模型选择和 JWT 密钥由一个配置模块统一校验。
- 同会话并发 SSE 不阻塞事件循环，单实例内轮次保持顺序。
- 单意图和多意图的政策答案都保留结构化 RAG 证据。
- 前后端 lint、test、build、OpenAPI 漂移和容器 smoke test 均进入 CI。
- `not_found`、`unavailable`、`stale`、`ambiguous` 不再共用空值语义。
- README、环境模板、Docker 注释、测试地图和实际行为一致。

## 领域不变量

- 保持现有 `collect-then-compose` 流程；图和 Agent 继续作为薄 adapter。
- 政策结论必须携带 RAG 证据；依赖不可用时明确返回不可用状态。
- 天气失败显式呈现，不用模型猜测。
- 12306 只使用官方公开入口和官方站点数据，不返回臆造车次、时刻、票价、余票或购买结果。
- `.env` 覆盖继承环境变量；保持已配置模型，不静默切换模型或密钥。
- `data/chroma/` 继续作为运行时状态，通过现有跨进程锁访问，不进入镜像源文件或 Git。

## 模块深化方向

本迭代减少调用方需要理解的接口，不以拆文件数量为目标：

- `Configuration.load() -> Settings` 隐藏 dotenv、默认值和校验顺序。
- `PolicyProvider.retrieve() -> PolicyResult` 隐藏 Chroma、Embedding 和错误分类。
- `Conversation.run/stream() -> ChatResult/Event` 隐藏锁、图事件和结果重建。
- 图 State 只携带领域结果，不传播外部 adapter 的异常或内部状态。

这些接口是测试面。LLM、Embedding、天气和 Postgres 只在内部 seam 使用生产 adapter 与测试
adapter，不为单一实现新增无收益的抽象层。

## 实施顺序

```text
01 配置/JWT ─────┬──> 04 生产镜像 ──> 05 全栈门禁 ──┐
                 └──> 06 结果与就绪语义 ────────────┤
02 证据汇总 ────────────────────────────────────────┤
03 会话并发 ────────────────────────────────────────┤
                                                    └──> 07 事实与文档收口
```

第一批可并行执行：01、02、03。04 在配置启动语义稳定后执行；05、06 完成后由 07 做最终事实
清账。每张票独立通过对应定向测试后，再进入后继票。

## 票据

| 票据 | 内容 | 优先级 |
|---|---|---|
| `01-runtime-config-jwt.md` | 统一配置加载与 JWT 启动校验 | P0 |
| `02-evidence-merge.md` | 修复多意图证据丢失 | P0 |
| `03-session-concurrency.md` | 修复 SSE 阻塞锁与锁生命周期 | P0 |
| `04-production-image.md` | 构建完整生产镜像 | P0 |
| `05-fullstack-gate.md` | 建立前端、契约和容器门禁 | P1 |
| `06-outcome-readiness.md` | 统一依赖结果和运维状态 | P1 |
| `07-product-facts-docs-db.md` | 清理票务事实、文档和数据库漂移 | P1/P2 |

## 非目标

- 新增 Agent、意图、票务购买、航班实时数据或用户功能。
- 多实例会话顺序、分布式锁、共享熔断器或插件广播。
- OAuth、RBAC、Postgres 高可用、备份平台或完整可观测性平台。
- 为了形式统一重写 LangGraph、RAG 或前端技术栈。

## 总体验收

- `scripts/gate.sh` 包含并通过后端与前端快速门禁。
- 容器 smoke test 验证 `/`、静态资源、`/livez`、`/readyz` 和 RAG 文档存在。
- 新增并发与多意图证据回归测试，修复前能够稳定失败，修复后通过。
- `rg` 不再发现 `xiao_wen.system`、InMemory 兜底、浮动 Postgres 版本或用户可见固定车次票价。
- 有有效凭据时运行 `scripts/gate.sh --full`；无凭据或供应商故障时记录未运行原因，不把它计为通过。
- 更新 `summary.md`、README、环境模板、ADR/运行约束和测试地图。

