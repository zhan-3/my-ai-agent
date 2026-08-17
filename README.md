# 差旅“晓问”——智能出行助手

基于 LangGraph、FastAPI 和 React 的多 Agent 差旅助手。当前主管使用注册表驱动的一次性
`classify → route → execute → merge` Workflow；行程子 Agent 内部使用 `collect-then-compose`。
系统提供行程规划、偏好与历史记忆、政策知识问答、天气查询和 12306 官方查询链接，运行时记忆与
用户数据统一存储在 PostgreSQL 16。

## 能力边界

- **行程建议**：模型生成逐日安排；缺少城市、日期或天数时先澄清，不硬生成。
- **政策事实**：只能引用本轮 RAG 证据；无命中与依赖不可用具有不同结果语义。
- **费用估算**：仅提供非报价、非公司政策的住宿与餐饮规划档；交通金额不估算。
- **12306**：只生成官方公开入口链接，使用官方站点数据并校验日期；不查询或编造车次、
  时刻、余票、票价、订单和购买结果。
- **运行边界**：当前支持单应用实例；不承诺跨实例会话顺序、缓存或熔断状态一致。

完整分型见 [`docs/capability-matrix.md`](docs/capability-matrix.md)。

## 快速开始

需要 Python 3.11、[uv](https://docs.astral.sh/uv/)、Node.js 22、pnpm 11 和 Docker。

```bash
cp .env.example .env
# 填写 LLM、Embedding、JWT_SECRET 和 POSTGRES_URL
uv sync --frozen --all-groups
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
docker compose up -d postgres
uv run python -m xiao_wen.webapp
```

本地默认数据库连接串：

```dotenv
POSTGRES_URL=postgresql://postgres:123456@localhost:5432/xiao_wen
DEEPSEEK_MODEL=deepseek-v4-flash
```

打开 `http://127.0.0.1:8000`；API 文档位于 `http://127.0.0.1:8000/docs`。
前端联调可运行 `pnpm --dir frontend dev`，Vite 使用 5173 端口并代理后端 API。

## 测试与质量门禁

提交前门禁只保留确定性后端检查：Ruff lint/format、非集成 pytest 和 mypy。测试绝不回退到
开发库，首次运行先创建专用测试库：

```bash
scripts/init_test_db.sh
export POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test
scripts/gate.sh
```

CI 独立运行前端 lint/test/build；OpenAPI 漂移在 HTTP 契约变化时按需检查；镜像 smoke 只在
主分支和手动触发时运行。真实模型和意图契约均为按需诊断，不阻塞日常提交。命令与保留范围见
[`docs/test-map.md`](docs/test-map.md)。

## 容器部署

```bash
docker compose up -d --build
```

- `/livez`：仅报告进程存活，不访问外部依赖。
- `/readyz`：只读检查配置、Postgres、RAG 文档和前端静态资源；未就绪返回 503。
- `/healthz`：兼容入口，语义与 `/readyz` 相同。

Compose、CI 与镜像 smoke 均固定 PostgreSQL 16。旧浮动版本卷若由更高 major
创建，不能直接降级挂载；保留数据时先用原版本执行 `pg_dump`，再导入新的 16 卷。详见
[`ADR-0006`](docs/adr/ADR-0006-postgres-memory.md)。

## 架构与文档

- `src/xiao_wen/`：领域深模块、会话循环、图工厂、Agent 薄适配器和 Web API。
- `frontend/`：React/Vite 客户端及 Vitest 测试。
- `tests/`：后端契约、单元与真实模型集成测试。
- `docs/documents/`：政策 RAG 原始语料；`data/chroma/` 仅为本地运行状态。
- [`CONTEXT.md`](CONTEXT.md)：领域术语与不变量。
- [`docs/test-map.md`](docs/test-map.md)：测试分层与执行入口。
- [`docs/adr/`](docs/adr/)：关键架构决策。
- [`.scratch/agent-loop/spec.md`](.scratch/agent-loop/spec.md)：当前最高优先级与实施票据。

## 已知限制与后续优化

- 当前在主管图外已有有界对话状态层：每个前端对话使用独立 `conversation_id`，线程 transcript
  与用户长期记忆分离；未完成行程可被偏好、政策或实时查询打断并继续，“新对话”不会继承旧 transcript。
- 当前主管仍是 `classify → route → execute → merge` 的一次性 Workflow，不把它描述为真正的 Agent。
- 下一阶段最高优先级是借鉴 Pi 的 Agent Loop，将主管升级为
  `decide → 调用子 Agent → observe → decide → final`；现有子 Agent、注册中心和行程
  `collect-then-compose` 流程保留为领域执行器。
- 政策证据、票务事实、天气失败和写回前验证继续作为确定性策略门，不能被主管模型绕过。
- 循环必须限制步骤、时间和 token，并持久化目标、已知差旅要素、待回答问题与工具观察；不能用
  装饰性 `while` 或无限自治替代可验证的终止条件。
- 多实例会话顺序、数据库 migration、连接池和高可用仍属于后续独立设计。

本地调试可在 `.env` 设置 `OBSERVABILITY_DEBUG=true`。同步与 SSE 对话会按轮追加到
`data/observability/turns.jsonl`，包含意图、子任务、Agent 输出、证据、最终结果和错误；文件权限
限制为当前用户，且被 Git 忽略。记录中不包含请求头、JWT、密码或 API Key，但包含真实对话文本，
只应用于专门测试账号并按需删除。
