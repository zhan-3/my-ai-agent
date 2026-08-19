# 差旅“晓问”——智能出行助手

基于 LangChain、FastAPI 和 React 的多 Agent 差旅助手。主管使用注册表驱动的有界
`decide → 调用子 Agent → observe → decide → final` Loop；行程子 Agent 内部使用 `collect-then-compose`。
系统提供行程规划、偏好与历史记忆、政策知识问答、联网查询（天气/空气质量/当地时间·时差/汇率），运行时记忆与
用户数据统一存储在 PostgreSQL 16。

## 能力边界

- **行程建议**：模型生成整体行程（去程/住宿/返程 + 每日要点）；长差（>5 天）空白日折叠，餐饮偏好只提示一次不逐日重复；缺少城市、日期或天数时先澄清，不硬生成。
- **政策事实**：只能引用本轮 RAG 证据；无命中与依赖不可用具有不同结果语义。
- **费用估算**：仅提供非报价、非公司政策的住宿与餐饮规划档；交通金额不估算。**境外目的地**（非 `Asia/Shanghai` 时区）不显示人民币金额，标注「以当地差旅政策为准」。
- **实时事实**：天气/空气仅在出发日处于 7 天预报窗口内时查询，超窗静默跳过；PM2.5 ≥ 75 才触发空气质量提醒；跨时区（时差非 0）才提示时差。失败显式呈现，不编造。
- **票务边界**：不生成购票链接、不查询或编造车次/时刻/余票/票价，购票与票务查询由商旅平台承担。
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

打开 `http://127.0.0.1:8000`；本地开发库测试账号 `tester / test123456`。API 文档位于 `http://127.0.0.1:8000/docs`。
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
主分支和手动触发时运行。真实模型检查为按需诊断，不阻塞日常提交。命令与保留范围见
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

- `src/xiao_wen/`：领域深模块、主管 Agent Loop、子 Agent 薄适配器和 Web API。
- `frontend/`：React/Vite 客户端及 Vitest 测试。
- `tests/`：后端契约、单元与真实模型集成测试。
- `docs/documents/`：政策 RAG 原始语料；`data/chroma/` 仅为本地运行状态。
- [`CONTEXT.md`](CONTEXT.md)：领域术语与不变量。
- [`docs/test-map.md`](docs/test-map.md)：测试分层与执行入口。
- [`docs/adr/`](docs/adr/)：关键架构决策。
- [`.scratch/agent-loop/spec.md`](.scratch/agent-loop/spec.md)：当前最高优先级与实施票据。

## 已知限制与后续优化

- 每个前端对话使用独立 `conversation_id`，工具 transcript 与用户长期记忆分离；未完成行程可被
  偏好、政策或实时查询打断并继续，“新对话”不会继承旧 transcript。
- 主管 Loop 限制步骤、时间、token 和重复调用；政策证据、票务事实、天气失败及写回前验证由
  确定性策略门约束，不能被主管文本覆盖。
- 第一版不实现运行中 steering/follow-up 队列、自动上下文压缩或完整 Session 树。
- 多实例会话顺序、数据库 migration、连接池和高可用仍属于后续独立设计。

本地调试可在 `.env` 设置 `OBSERVABILITY_DEBUG=true`。同步与 SSE 对话会按轮追加到
`data/observability/turns.jsonl`，包含意图、子任务、Agent 输出、证据、最终结果和错误；文件权限
限制为当前用户，且被 Git 忽略。记录中不包含请求头、JWT、密码或 API Key，但包含真实对话文本，
只应用于专门测试账号并按需删除。
