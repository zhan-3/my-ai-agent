# 差旅"晓问"——智能出行助手

## 项目简介

企业差旅场景的多 Agent 智能助手。主管 Agent 采用有界 **Agent Loop**（`decide → 调用子 Agent → observe → decide → final`）自主编排 6 个内置子 Agent + 1 个外部扩展，提供**行程规划、政策知识问答（RAG）、偏好与历史记忆、联网查询**四大能力。行程子 Agent 内部使用 `collect-then-compose` 两阶段生成（要素提取 → 行程生成）。

系统遵循严格能力边界：政策结论必须携带 RAG 证据、天气失败显式呈现不编造、不代购票（票务由商旅平台承担）、境外差旅不显示人民币金额。运行时记忆与用户数据统一存储在 PostgreSQL 16。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11 · FastAPI · LangChain（OpenAI 兼容 LLM 接缝）· uv 依赖管理 |
| 前端 | React 19 · TypeScript · Vite · Tailwind CSS 4 · Vitest · Oxlint |
| 数据 | PostgreSQL 16（用户/偏好/行程/对话统一存储）· ChromaDB（RAG 向量索引，运行时状态） |
| 实时事实 | 免费无 key 公开 API（天气/空气质量/汇率/时区换算） |
| 部署 | Docker Compose · GitHub Actions CI（后端 gate + 前端检查 + 镜像 smoke） |

## 系统架构

```text
浏览器 (React/Vite)
      │  SSE 流式 / REST
      ▼
FastAPI Web 层 (webapp.py) ── JWT 认证 ──► 会话 (session.chat)
                                              │
                                              ▼
                              主管 Agent Loop (有界：步骤/时间/token 限制)
                         decide → 调用子Agent → observe → decide → final
                                              │
                              注册中心 (plugin_registry：manifest 懒加载)
   ┌────────┬────────┬────────┬────────┬────────┬────────┐
行程规划  偏好记录  历史查询  知识问答  联网查询   其他    差旅统计(插件)
   │        │        │        │        │        │
trip_planner 记忆层   记忆层   RAG      web 工具  会话层
   │        │        │        │        │        │
   └────────┴────────┴────────┴────────┴────────┘
                   PostgreSQL 16（唯一持久化后端）
```

**记忆分层**：短期对话记忆按线程（`thread_id`）隔离；长期偏好/历史行程按用户（`user_id`）隔离。策略门（政策证据、天气失败、写回前验证）由确定性代码执行，主管文本不能覆盖。

## Agent 列表与职责说明

| Agent | 意图 | 职责 |
|---|---|---|
| 行程规划 | 行程规划 | `collect-then-compose`：提取差旅要素（城市/日期/天数/人数/返程/预算）→ 缺项澄清 → 生成整体行程（去程/住宿/返程 + 每日要点）→ 日期/天数/政策证据校验 → 写回 trips 表 |
| 偏好记录 | 偏好记录 | 从对话中提取住宿/餐饮/交通/预算/常驻城市等偏好，追加或覆盖写入长期记忆 |
| 历史查询 | 历史查询 | 按用户查询历史行程档案与差旅画像（次数/城市/预算汇总） |
| 知识问答 | 知识问答 | 从 8 份政策语料（差旅标准/报销/订票/FAQ/应急/平台/城市提示/绿色倡议）做 RAG 检索回答，携带证据来源 |
| 联网查询 | 联网查询 | 工具调用：天气（含紫外线/体感/风速）、空气质量（PM2.5）、当地时间/时差、汇率 |
| 其他 | 其他 | 非差旅业务意图、行程取消等通用处理 |
| 差旅统计（插件） | 差旅统计 | 外部扩展示例，动态并入注册中心 |

## 核心示例

**行程规划**（用户明确日期/城市/天数 → 直接生成）：

```text
用户：帮我规划10月8日去北京开会4天的行程
晓问：📋 本次为北京开会出差，10月8日出发，共4天
      💡 安排理由：……
      🚄 去程：10月8日 抵达北京后入住酒店
      🏨 住宿：……
      🚄 返程：10月11日
      📌 行程安排：10月8日 抵达入住；10月9-10日 开会；10月11日 返程
      💰 预算：经济/中等/舒适三档（非报价、非公司政策）
      ⚠️ 应急提醒 ／ 📌 政策依据（带 RAG 来源）
```

**政策问答**：

```text
用户：出差住宿标准是什么？
晓问：根据《差旅标准》……（来源：01_travel_standards.txt，标注 grounded）
```

**偏好记忆**（跨对话自动生效）：

```text
用户：我不吃辣，住宿喜欢安静
晓问：已记住：餐饮偏好【不吃辣】、住宿偏好【喜欢安静】，下次规划行程自动生效
```

## 快速开始（运行方式）

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

打开 `http://127.0.0.1:8000`；本地开发库测试账号 `tester / test123456`。API 文档位于 `http://127.0.0.1:8000/docs`。前端联调可运行 `pnpm --dir frontend dev`，Vite 使用 5173 端口并代理后端 API。

**能力边界**：行程缺城市/日期/天数先澄清不硬生成；长差（>5 天）空白日折叠，餐饮偏好只提示一次不逐日重复；境外目的地不显示人民币金额（以当地差旅政策为准）；天气/空气仅在出发日 7 天预报窗口内查询；票务（车次/余票/购票）由商旅平台承担，晓问不代购。

## 关键设计说明

- **有界 Agent Loop**（[ADR-0010](docs/adr/ADR-0010-supervisor-agent-loop.md)）：主管按 `decide → 调用子 Agent → observe → decide → final` 自主循环，受步骤/时间/token/重复调用限制；取消时停止且不提交不完整结果。
- **注册中心驱动**（[ADR-0005](docs/adr/ADR-0005-plugin-boundary.md)）：`plugin_registry` 扫描内置 `agents/` + 外部 `plugins/` 生成 manifest（AST 只读元数据、零加载），派发时才懒加载，内置优先。
- **行程生命周期四态**（[ADR-0011](docs/adr/ADR-0011-trip-lifecycle.md)）：统一 `trips` 表，`drafting → upcoming → completed / cancelled`；completed 读时按日期派生；改期更新同一条、参考再来一次复制新行程。
- **行程呈现策略**（[ADR-0012](docs/adr/ADR-0012-trip-presentation.md)）：整体结构（去程/住宿/返程 + 📌 要点）；餐饮退出逐日；长差折叠由代码层 `_GENERIC_ACTIVITIES` 过滤兜底，不依赖 LLM 自觉。
- **确定性策略门**：政策结论必须携带本轮 RAG 证据；无命中/依赖不可用有不同结果语义；天气失败显式呈现；写回前验证（日期/天数/返程不早于出发）。
- **政策数字分层**：金额/时限等"硬伤"由代码读 RAG facts；渠道/流程等"软伤"由 LLM 回答；RAG 不可用时不显示金额。
- **深模块 + 薄适配**（[ADR-0003](docs/adr/ADR-0003-trip-planner.md)）：`trip_planner.py` 封装提取/补全/缺项/生成/验证/写回/展示；子 Agent 只做 `collect-then-compose` 薄适配。

## 已完成基础项

- [x] 用户注册/登录与账号隔离（JWT 认证，用户数据互不可见）
- [x] 多 Agent 智能助手架构（主管 + 子 Agent 分工协作）
- [x] 差旅行程规划全流程（要素提取 → 缺项澄清 → 生成 → 校验 → 落库）
- [x] 政策知识问答（8 份企业差旅文档 RAG 检索，带证据来源）
- [x] 偏好与常驻城市记忆（追加/覆盖，跨会话自动生效）
- [x] 历史行程查询与管理（档案、差旅画像、取消/改期）
- [x] PostgreSQL 持久化（用户/偏好/行程/对话统一存储）
- [x] 前端交互界面（登录、对话、行程卡片、记忆侧栏）

## 已完成加分项

- [x] 主管**有界 Agent Loop** 自主决策（非固定路由，可观察子 Agent 结果继续决策）
- [x] 子 Agent **动态注册中心**（自动扫描、懒加载、渐进式披露，外部扩展动态并入）
- [x] **联网查询**工具（天气含紫外线/体感/风速、空气质量 PM2.5、当地时间/时差、汇率）
- [x] **SSE 流式回复** + 行程卡片结构化渲染（继续对话/改期/取消操作）
- [x] 行程**生命周期管理**（规划中/待出发/已完成/已取消四态）
- [x] 行程**呈现策略**（长差折叠、餐饮退出逐日、境外预算以当地政策为准）
- [x] **确定性策略门**（政策证据、天气失败、写回验证不能被主管文本覆盖）
- [x] 对话细节**回归集**（28 个真实 LLM 用例，防漏洞回潮）+ 后端 264 确定性测试 + 前端 42 测试

## 已知问题与后续优化方向

- **汇率换算**：已具备汇率工具但暂未接入行程预算换算（记入待办，暂不排期）。
- 每个前端对话使用独立 `conversation_id`，工具 transcript 与长期记忆分离；"新对话"不继承旧 transcript。
- 第一版不实现运行中 steering/follow-up 队列、自动上下文压缩或完整 Session 树。
- 多实例会话顺序、数据库 migration、连接池和高可用属于后续独立设计。
- 长差中间日如用户无具体安排，展示层折叠为"其余 N 天"，未来接入地图/POI 数据可扩展逐日内容。

## 测试与质量门禁

提交前门禁只保留确定性后端检查（Ruff lint/format、非集成 pytest、mypy），测试绝不回退开发库：

```bash
scripts/init_test_db.sh
export POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test
scripts/gate.sh
```

CI 独立运行前端 lint/test/build；镜像 smoke 只在主分支运行。真实模型检查为按需诊断。详见 [`docs/test-map.md`](docs/test-map.md)。

## 容器部署

```bash
docker compose up -d --build
```

- `/livez`：仅报告进程存活；`/readyz`：只读检查配置、Postgres、RAG 文档和前端静态资源；`/healthz`：兼容入口，语义与 `/readyz` 相同。
- Compose、CI 与镜像 smoke 均固定 PostgreSQL 16（详见 [ADR-0006](docs/adr/ADR-0006-postgres-memory.md)）。

## 日志与排障

日志双写：`data/stability.log`（按天滚动保留 7 天，git 忽略）+ stdout（前台运行时在终端，`nohup` 启动进 `nohup.out`，容器部署进 `docker logs`）。级别 INFO+，`httpx` 库噪音已静音；业务链路日志按 `xiao_wen.*` 模块名区分（`agent_loop` / `trip_planner` / `web` / `llm` / `memory_pg` / `dialogue`），出问题先查该文件。

## 项目目录结构

```text
.
├── README.md                   # 项目说明（本文件）
├── CONTEXT.md                  # 领域术语与不变量
├── AGENTS.md                   # Agent 协作约定
├── .env.example                # 环境变量模板
├── pyproject.toml / uv.lock    # 后端依赖与工具配置
├── Dockerfile                  # 容器镜像
├── docker-compose.yml          # Postgres + 应用编排
├── .github/workflows/ci.yml    # CI：后端 gate / 前端检查 / 镜像 smoke
│
├── src/xiao_wen/               # 后端领域深模块
│   ├── agent_loop.py           # 主管有界 Agent Loop
│   ├── plugin_registry.py      # 子 Agent 注册中心（manifest 懒加载）
│   ├── session.py / dialogue.py  # 会话闭环与对话编排
│   ├── webapp.py               # FastAPI Web/SSE 层
│   ├── auth.py                 # JWT 认证
│   ├── trip_planner.py         # 行程规划深模块（提取/生成/校验/展示）
│   ├── validation.py           # 行程校验（日期/返程/天数）
│   ├── memory.py / memory_pg.py  # 记忆接口 / Postgres 后端（trips 表）
│   ├── rag.py                  # 政策 RAG 检索
│   ├── llm.py                  # LLM 接缝（熔断/重试）
│   ├── web.py                  # 联网查询工具（天气/空气/时差/汇率）
│   ├── reference_data.py       # 城市/时区/空气参考数据
│   ├── stats.py                # 差旅画像统计
│   ├── observability.py        # 对话观察日志
│   └── agents/                 # 6 个子 Agent 薄适配
│       ├── itinerary_agent.py  # 行程规划（collect-then-compose）
│       ├── preference_agent.py # 偏好记录
│       ├── history_agent.py    # 历史查询
│       ├── knowledge_agent.py  # 知识问答（RAG）
│       ├── web_agent.py        # 联网查询
│       └── other_agent.py      # 其他
│
├── plugins/
│   └── stats.py                # 差旅统计（外部扩展，动态注册）
│
├── frontend/                   # React 前端
│   ├── package.json / vite.config.ts
│   └── src/
│       ├── App.tsx / main.tsx
│       ├── api/                # auth/chat/memory/stats/contract
│       ├── hooks/              # useAuth / useChat（SSE）
│       ├── components/         # ChatShell / TripCard / MemorySidebar / AuthPanel…
│       ├── lib/                # trip 解析 / agents 定义 / theme
│       └── test/               # Vitest 测试（42 用例）
│
├── tests/                      # 后端测试
│   ├── test_agent_loop.py / test_itinerary.py / test_memory_pg.py…
│   └── test_dialogue_regression.py  # 对话细节回归集（28 个真实 LLM 用例）
│
├── scripts/
│   ├── gate.sh                 # 确定性门禁（ruff/format/pytest/mypy）
│   ├── init_test_db.sh         # 测试库初始化
│   ├── generate_openapi.py     # OpenAPI 生成
│   └── smoke_image.sh          # 镜像 smoke 测试
│
├── docs/
│   ├── capability-matrix.md    # 能力分型与边界
│   ├── test-map.md             # 测试分层与执行入口
│   ├── adr/                    # 14 篇架构决策（ADR-0001 ~ ADR-0014）
│   ├── agents/                 # Agent 协作机制文档
│   └── documents/              # 8 份政策 RAG 语料
│
└── data/                       # 运行时状态（chroma 索引/锁/日志，git 忽略不提交）
```

## 相关文档

- [`CONTEXT.md`](CONTEXT.md)：领域术语与不变量。
- [`docs/capability-matrix.md`](docs/capability-matrix.md)：能力分型与边界。
- [`docs/test-map.md`](docs/test-map.md)：测试分层与执行入口。
- [`docs/adr/`](docs/adr/)：关键架构决策（12 篇）。

本地调试可在 `.env` 设置 `OBSERVABILITY_DEBUG=true`，同步与 SSE 对话会按轮追加到 `data/observability/turns.jsonl`（不含请求头/密码/Key，仅用于专门测试账号，被 Git 忽略）。
