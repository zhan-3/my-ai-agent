# 项目全面评估与收敛建议

评估日期：2026-08-17  
评估范围：后端、前端、测试、评测、配置、安全、Docker、CI、数据库与项目文档。

## 结论

晓问已经具备成熟原型的主体能力：领域边界清楚，`collect-then-compose` 编排、契约模型、
Postgres 用户隔离、RAG 证据、官方 12306 链接与确定性验证均有实现和测试支撑。

当前短板不在功能数量，而在**交付闭环与产品事实一致性**。代码、文档、测试和镜像描述的
还不是同一个系统，且存在少数测试未覆盖的生产阻断问题。建议暂停新增能力，完成一次收敛
迭代，把目标限定为：

> 单实例、低并发、可部署的内部试点；行为有证据、故障可辨识、镜像可独立运行。

本轮不承诺多实例一致性、分布式锁、OAuth、数据库高可用或大规模并发。

## 已验证基线

| 项目 | 结果 |
|---|---|
| Ruff lint / format | 通过 |
| mypy | 71 个源文件无问题 |
| 后端非集成测试 | 286 通过，22 个真实 LLM 测试未运行 |
| 前端构建 | 通过 |
| 前端测试 | 31 通过 |
| 前端 lint | 完成，7 条 Fast Refresh warning |
| 最近 holdout 报告 | 42/42，通过；属于 2026-08-15 历史结果 |

“非集成测试通过”与“真实模型能力已验证”必须分别报告，不把未运行呈现为全绿。

## 风险分级

### P0：阻断完整交付

#### 1. 生产镜像缺少前端与 RAG 语料

`Dockerfile` 只复制 `src/`、`plugins/` 和 README，没有构建或复制 `frontend/dist`，也没有
复制 `docs/documents`。镜像虽然能构建，但访问 `/` 只能看到“前端未构建”，政策问答也无法
从语料重建索引。CI 当前只验证镜像构建成功，没有运行时 smoke test。

#### 2. 配置初始化与 JWT 密钥不可靠

`auth.py` 在 `.env` 加载前读取 `JWT_SECRET`，本地 `uv run xiao-wen` 可能继续使用公开开发
密钥。`llm.py`、`rag.py` 等调用默认 `load_dotenv()`，继承环境变量仍优先于 `.env`，与仓库
“`.env` 优先”约束冲突。空密钥、短密钥和生产默认密钥也没有统一启动校验。

#### 3. SSE 同会话并发可能阻塞事件循环

`session.stream_chat()` 在异步生成器中直接调用 `threading.Lock.acquire()`，随后等待异步图
事件。第二个同会话请求可能阻塞事件循环，使第一个请求无法继续并释放锁。现有测试只覆盖
同步 `chat()` 的线程串行化，没有覆盖两个并发流或 `chat` 与 `stream_chat` 交错。

#### 4. 多意图汇总丢失 RAG 证据

并行节点把 `sources` 放入 `collected`，但 `graph_builder.merge()` 只合并
`plan/stats/history`。因此“知识问答 + 其他请求”的最终答案可能包含政策结论，却没有结构化
证据，违反“政策结论必须携带 RAG 证据”的领域约束。

### P1：影响可信度与质量门禁

#### 5. 产品事实来源仍有冲突

`reference_data.py` 保存固定车次和票价，预算块会输出“参考车次”和具体金额；README 又称其
为“真实高铁车次/票价”。即使标注参考价，这些数据仍会过期，也不符合票务事实必须来自官方
入口的严格约束。预算估算、实时事实、政策事实和模型建议需要明确分型。

#### 6. 前端未进入正式门禁

前端已有 7 个测试文件，但 `frontend/package.json` 没有 `test` script，`scripts/gate.sh` 和 CI
均未运行前端 lint、test、build，也未验证 OpenAPI 生成文件是否漂移。当前是“双栈项目、
单栈门禁”。

#### 7. 故障与业务无结果混用

行程上游的政策、指南、历史和本轮偏好在异常时常降级为空；`retrieve_policy()` 也会把依赖
异常折叠成无命中。调用方无法可靠区分 `not_found` 与 `unavailable`。直接知识问答路径会抛出
异常，因此问题不是“所有 RAG 都静默失败”，而是**不同入口错误语义不一致**。

#### 8. 健康检查缺少运维语义

`/healthz` 即使 Postgres、配置或 Chroma 异常仍返回 HTTP 200，只在 JSON 中给出警告；同步
聊天失败也返回正常 `ChatResponse(intent="error")`。容器和客户端无法区分存活、就绪、业务
无结果和系统故障。

### P2：限制后续演进

#### 9. 数据库生命周期仍是原型级

当前使用 `CREATE TABLE IF NOT EXISTS`、每操作短连接、文本时间字段和有副作用的健康检查；
Compose 使用 `postgres:latest`，CI 使用 PostgreSQL 16，卷注释又针对 18。版本、初始化、
升级和回滚策略尚未统一。

#### 10. 运行时状态只支持单实例语义

图缓存、意图词汇表、插件缓存、熔断器、后端单例和会话锁均为进程内状态。多 worker 下不能
保证同会话顺序、热插拔视图或熔断状态一致。当前可明确支持单实例，而不是声称多实例不可
运行；横向扩展属于后续独立设计。

#### 11. 文档是过期缓存

README 同时出现 132、210 等测试数量，引用已删除的 `xiao_wen.system`，并把 React 前端描述
为原生 HTML/JS；`Dockerfile` 和 `.env.example` 仍写内存后端。手写测试数量、完整文件树和
完成状态会持续漂移，应改成稳定入口、能力边界和自动生成报告。

## 架构判断

注册表、图工厂、会话循环和行程规划仍是有价值的深模块，不建议为了“变小”继续拆文件。
问题在于调用方需要理解的接口正在变宽：图 State 字段、错误空值、顺序约束和多层转换不断
增加。收敛方向是缩小接口并隐藏实现细节：

- `Configuration.load() -> Settings`：统一 `.env`、校验和运行模式。
- `PolicyProvider.retrieve(query) -> PolicyResult`：明确 grounded/not-found/unavailable/stale/ambiguous。
- `TripPlanner.plan(request) -> PlanningOutcome`：隐藏检索、预算、天气、验证和写回顺序。
- `Conversation.run/stream(turn) -> ChatResult/Event`：统一同步与流式结果、证据和故障语义。

接口是后续测试面；内部 seam 可替换外部 LLM、Embedding、天气和 Postgres adapter，但不应把
这些实现细节暴露给图或 Web 调用方。

## 收敛顺序

1. 修复配置/JWT、SSE 并发、证据汇总和镜像资产四个 P0。
2. 把前端、容器 smoke test 和契约漂移检查纳入门禁。
3. 统一 RAG 结果状态、readiness 和 HTTP 错误语义。
4. 清理固定票务事实、过期文档、Postgres 版本和测试库初始化。
5. 完成全量门禁；真实 LLM 无凭据或供应商故障时明确记录 `not-run` 或 `operational-failure`。

具体规格、依赖和验收条件见 `.scratch/convergence/spec.md` 及其 issues。完成标准不是“代码已
修改”，而是：

> 文档说的、代码做的、测试证明的、镜像交付的，成为同一个系统。
