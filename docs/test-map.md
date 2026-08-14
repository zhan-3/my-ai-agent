# 测试地图（答辩速查）

分层测试共 210 个：**单元层 190**（无 LLM，秒级，`uv run pytest -m "not integration"`）+ **集成层 20**（真实模型，`uv run pytest -m integration`，push 时 CI 跑）。

**记忆 = Postgres 唯一后端**：所有测试（含单元层）都连真实 Postgres——conftest 每测试清空记忆三表 + users 表并注入全新 PostgresBackend，优先 `POSTGRES_TEST_URL`（独立测试库），其次 `POSTGRES_URL`，两者皆无则 `pytest.fail`（CI 两个 job 都已配 postgres:16 服务 + `POSTGRES_TEST_URL`）。

| 测试文件 | 测什么 | 被问时一句话 |
|---|---|---|
| `conftest.py` | 每测试注入全新 PostgresBackend 并清四张表 | 「测试全部落到真实 Postgres，用例互不污染」 |
| `test_intent.py` | 意图识别 7 用例含边界（集成） | 「验证主管把自然语言正确分类到意图，边界请求正确拒绝」 |
| `test_llm.py` | 模型单例 + 熔断守卫代理 | 「验证模型只构造一次，坏了走熔断不裸崩」 |
| `test_memory.py` | 记忆追加/覆盖/常驻城市/历史 | 「验证偏好可新增、同类别覆盖不重复，常驻城市能补出发地」 |
| `test_memory_backend.py` | 后端协议：Postgres 直测 + 会话隔离矩阵 + 缺 URL 报错 | 「验证唯一后端 Postgres 的读写语义与用户隔离，缺配置明确报错」 |
| `test_memory_pg.py` | Postgres 真库读写 + 用户隔离 | 「验证落库持久化和按用户隔离」 |
| `test_auth.py` | bcrypt 密码哈希 / JWT 签验 / 注册登录（真实 users 表） | 「验证密码不落明文、令牌能签能验、用户存 Postgres」 |
| `test_webapp.py` | 注册/登录/me 端点 + 聊天用户隔离 | 「验证登录后只能读写自己的会话数据」 |
| `test_itinerary.py` | 行程要素缺失检查 + 结果格式 | 「验证要素不全时先向用户索取，不硬编行程」 |
| `test_plugin.py` | 注册中心：发现/懒加载/内置优先/热插拔 | 「验证新子 Agent 丢个文件就被自动发现，未用模块不加载」 |
| `test_rag.py` | RAG 分块（单元）+ 向量检索（集成） | 「验证知识库切片和相似度检索命中」 |
| `test_stability.py` | 熔断三态/重试/兜底 | 「验证 LLM 失败自动重试、熔断后优雅降级」 |
| `test_graph_builder.py` | 图工厂：图结构/指纹缓存/热插拔 | 「验证图按注册表动态组装，子 Agent 变了自动重建」 |
| `test_scheduler.py` | 并行调度组件（fan-out/fan-in） | 「验证多意图拆开后并行执行、结果归并」 |
| `test_session.py` | 会话循环：读记忆→注入→invoke→写回 | 「验证每轮对话的完整闭环」 |
| `test_web.py` | 联网查询（天气/汇率/空气质量工具调用） | 「验证工具调用链路、未来 7 天预报日期解析和降级文案」 |
| `test_endtoend.py` | 两层记忆闭环 + 外部扩展派发 + 多意图并行（集成） | 「验证从输入到结果整条链路端到端」 |
| `test_intent_split.py` | 子任务拆分兜底 + 归一化（stub 模型，确定性） | 「验证一句话多个请求能拆成主导+次要，不吞「顺便X」」 |
| `test_eval_metrics.py` | 评测指标：混淆矩阵/精确率召回率 F1/汇总 | 「验证评测系统纯函数指标正确」 |

## 答辩时的三句话

1. **为什么分两层**：单元层不碰真实 LLM，秒级、可离线自检，保证提交前自检快；集成层只有配了模型 Key 才跑（CI 里用 secrets 控制，fork PR 自动跳过防泄露）。记忆不是 mock——单后端化后单元层也打真实 Postgres（CI 自带 postgres 服务，本地 `docker-compose up -d postgres` 即可）。
2. **怎么保证质量**：提交前跑 4 条门禁——`ruff check`（lint）→ `ruff format --check`（格式）→ `pytest -m "not integration"`（单元）→ `mypy`（类型），全绿才打包；CI 每次 push 自动跑同样的门禁 + 真 LLM 集成层 + 黄金意图回归（阈值 0.95）+ Docker 镜像构建。
3. **测试覆盖了什么**：从底向上覆盖记忆（Postgres 协议 + 隔离）、认证、注册中心、稳定性、图工厂、会话、联网、RAG、评测指标，再往上 20 个集成用例打通意图识别、外部扩展派发、多意图并行的端到端链路。
