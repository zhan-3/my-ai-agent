# 差旅"晓问" —— 智能出行助手 Agent

一个基于 **LangGraph 多 Agent 架构**的企业差旅智能助手：用户用自然语言提出差旅需求，系统通过「意图识别 → 调度 → 专职 Agent 协作」完成**行程规划、偏好记忆、历史查询、政策知识问答、实时信息查询**等任务。

> 演示环境与代码：本仓库即完整项目。核心演示入口：`uv run python -m xiao_wen.system`

---

## 1. 项目简介

差旅场景有明确的**多角色分工**特点：识别用户要什么（意图）→ 决定派谁去做（调度）→ 各专职子 Agent 分别处理（规划行程 / 记偏好 / 查历史 / 答政策 / 查实时信息）。本项目把六个内置子 Agent（+ 外部扩展）作为**可动态发现的实体**（注册表扫描注册 / 懒加载 / 渐进式披露），由一个 LLM 意图主管统一调度，形成「**主管-子 Agent**」多 Agent 架构。

## 2. 技术栈

| 类别 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.11 | Agent 开发主流语言 |
| 编排框架 | LangGraph 1.2.10 | 状态图（StateGraph）、条件边、ToolNode、ReAct 循环 |
| LLM 框架 | LangChain / langchain-openai 1.4.2 | ChatOpenAI、结构化输出、@tool |
| 大模型 | DeepSeek（OpenAI 兼容接口） | 意图识别、要素提取、行程生成、问答、工具调用 |
| Embedding | 阿里 DashScope text-embedding-v3（1024 维） | 知识库向量化 |
| 向量库 | Chroma 1.5.9（磁盘持久化） | 政策文档语义检索 |
| 记忆存储 | Postgres 后端（`POSTGRES_URL`，psycopg）+ InMemory 演示兜底 | 短期对话 + 长期偏好/历史，**按用户隔离** |
| 认证 | JWT（pyjwt，HS256）+ bcrypt 密码哈希 | 注册/登录端点，会话维度 = 用户身份 |
| 联网数据 | open-meteo（天气/空气质量）、exchangerate-api（汇率） | 免费公开 API，无需 key |
| 包管理 | uv | 依赖锁定（pyproject.toml + uv.lock） |
| 类型检查 | mypy（dev 依赖） | 全项目 0 警告 |
| 代码检查 | ruff（dev 依赖） | E/F/I/UP/B/SIM 等规则全绿，门禁一部分 |
| 插件机制 | 子 Agent 注册中心 | 动态发现/懒加载/渐进式披露（内置+外部） |
| 稳定性层 | 自研 + LangChain 内置 | 重试/超时/熔断/兜底/日志/健康检查 |
| 测试框架 | pytest 9 + pytest.mark | 分层测试 130 个：单元 115（无 LLM，含 6 个 Postgres 条件跑）+ 集成 15（真实模型） |

## 3. 系统架构

```text
                          ┌─────────────────────────────┐
                          │   用户输入（自然语言）         │
                          └──────────────┬──────────────┘
                                         ▼
                          ┌─────────────────────────────┐
                          │  Intention Agent 意图识别     │
                          │  （LLM 动态词汇表 + json_mode） │
                          └──────────────┬──────────────┘
                                         │ 条件边：按意图路由
              ┌──────────────┬───────────┼───────────┬──────────────┐
              ▼              ▼           ▼           ▼              ▼
    ┌────────────────┐ ┌──────────┐ ┌────────┐ ┌────────────┐ ┌────────────┐
    │Itinerary Planning│ │Preference│ │ Memory  │ │Knowledge/  │ │Information │
    │  行程规划 Agent   │ │  偏好 Agent│ │Query Agent│ │RAG 知识 Agent│ │Query 联网Agent│
    │ 要素提取→行程生成 │ │ 追加/覆盖 │ │历史查询 │ │向量检索+生成│ │ToolNode ReAct│
    └────────────────┘ └──────────┘ └────────┘ └────────────┘ └────────────┘
              │                                                        │
              ▼                                                        ▼
    ┌──────────────────── 记忆层 ─────────────────────┐     ┌──────────────┐
    │ 短期：最近 6 轮对话（每轮注入）                    │     │ 免费公开 API   │
    │ 长期：偏好/常驻城市/历史行程（JSON 持久化）        │     │ 天气/汇率/空气 │
    └─────────────────────────────────────────────────┘     └──────────────┘
```

意图词汇表 = 注册表 manifest **动态生成**：六内置（`行程规划 / 偏好记录 / 历史查询 / 知识问答 / 联网查询 / 其他`）+ 外部扩展（如 `差旅统计`）自动并入——新增子 Agent 主管零改动（见 §6.7）。主管图由**图工厂**（graph_builder）组装，指纹缓存自动重建。产品边界规则：**仅服务企业差旅**，个人休闲旅游等一律归「其他」。

> 📌 更完整的代码层映射挂图（运行时 pipeline + 脚手架动机、逐文件速查）见 [docs/layer-map.html](docs/layer-map.html)。

## 4. Agent 列表与职责说明

系统的角色及其落地（六内置子 Agent 实体 + 外部扩展，由注册表动态发现）：

| 系统角色 | 系统实现 | 职责 | 关键技术 |
|---|---|---|---|
| Intention Agent 意图识别 | `classify_intent` 节点（intent.py） | 动态词汇表分类 + 理由 | LLM + json_mode 结构化输出 |
| Orchestration Agent 调度 | 条件边路由（graph_builder 图工厂组装） | 按意图把请求分派给对应子 Agent | `add_conditional_edges` |
| Event Collection Agent 要素提取 | 行程子 Agent 第一阶段 | 提取出发/目的/日期/时长/偏好 | LLM 结构化输出 |
| Itinerary Planning Agent 行程规划 | `agents/itinerary_agent.py` | 生成完整行程 | 两阶段管线 + 偏好注入 |
| Preference Agent 偏好 | `agents/preference_agent.py` | 偏好写入（追加/覆盖区分） | 长期记忆 |
| Memory Query Agent 记忆查询 | `agents/history_agent.py` | 返回历史行程 | 长期记忆 |
| Knowledge/RAG Agent 知识问答 | `agents/knowledge_agent.py` | 政策库语义检索 + 生成 | embedding + Chroma |
| Information Query Agent 联网查询 | `agents/web_agent.py` | 天气/汇率/空气质量 | ToolNode + ReAct 循环 |
| 边界兜底 Agent | `agents/other_agent.py` | 非差旅问题拒绝 | 词汇表校验兜底归「其他」 |
| 外部扩展子 Agent ★ | `plugins/stats.py` | 差旅画像（次数/总天数/年均/年度趋势/常去城市，注册表自动发现并入） | discover + 懒加载 |

## 5. 运行方式说明

```bash
# 1) 安装依赖（uv 管理）
uv sync

# 2) 配置 .env（复制模板并填入 Key；模板见 .env.example）
cp .env.example .env

# 3) 一键体验完整系统（推荐）
uv run python -m xiao_wen.system

# 4) 分模块验证各 Agent
uv run python -m xiao_wen.web            # 联网查询（工具调用）
uv run python -m xiao_wen.rag            # 知识问答（向量检索 + Chroma）
uv run python -m xiao_wen.scheduler      # 调度优化：多请求并行执行
uv run python -m xiao_wen.demos.plugin_demo    # 插件化架构：动态发现/懒加载/热插拔（四幕演示）
uv run python -m xiao_wen.demos.stability_demo # 工程稳定性：重试/熔断/故障注入/健康检查（四幕演示）
uv run ruff check              # 代码检查（lint，秒级；--fix 自动修复可修项）
uv run ruff format .           # 代码格式化（统一风格，可加 --check 只检查）
uv run mypy src/xiao_wen       # 类型检查（0 警告）
uv run pytest                  # 自动化测试：单元层（无 LLM，秒级）
uv run pytest -m integration   # 自动化测试：集成层（真实 LLM，约 1 分钟）
uv run xiao-wen                # 可视化 Web 界面（等价 python -m xiao_wen.webapp）→ http://127.0.0.1:8000
```

> 持久化记忆（可选）：`docker compose up -d postgres` 起本地 Postgres，然后
export POSTGRES_URL=postgresql://postgres:123456@localhost:5432/xiao_wen
即可让记忆落盘（用户隔离）；不设则用内存后端（演示，重启即失）。
> 已实测：本地容器 `my-postgres`（postgres:18）跑通注册/登录/偏好写入/用户隔离/重启后登录持久化，`test_memory_pg.py` 6 个真库测试全绿。
> 认证：打开 Web 界面先注册/登录（JWT）；生产环境务必 `export JWT_SECRET=<长随机串>` 覆盖开发默认密钥。

> 生产部署（Docker）：`docker compose up -d --build` 一条命令起全套
> （app + postgres），API keys 从 `.env` 注入；CI 见 `.github/workflows/ci.yml`。

> 首次运行 `xiao_wen.system` 中知识问答会构建向量索引（一次性，约 500 个文本块，随语料变化），之后复用磁盘索引，秒级返回。

### 目录结构

```text
.
├── README.md                    # 项目说明（本文件）
├── CONTEXT.md                   # 领域术语表（主管/子 Agent/注册中心…）
├── AGENTS.md                    # Agent 协作配置（本地 issue tracker 约定）
├── pyproject.toml               # 依赖与工具配置（uv 管理）
├── uv.lock                      # 依赖锁定
├── .gitignore                   # 忽略：.env / data 数据 / 交付包
├── .env.example                 # 环境变量模板（复制为 .env 填 Key）
├── .python-version
│
├── src/                         # 源码（src 布局）
│   └── xiao_wen/                ★ 成品包
│       ├── __init__.py          # 包元信息
│       ├── system.py            ★ 完整系统（单意图主管图，图工厂薄壳，主入口）
│       ├── scheduler.py         ★ 调度优化（并行调度图，图工厂薄壳）
│       ├── graph_builder.py     ★ 图工厂（主管/调度图组装 + 指纹缓存热插拔）
│       ├── session.py           ★ 会话循环收口（读记忆→注入→invoke→写回）
│       ├── intent.py            ★ 意图识别单一来源（动态词汇表 + 多意图拆分）
│       ├── llm.py               ★ 模型单一接缝（懒构造 + 熔断守卫代理）
│       ├── trip_planner.py      ★ 行程规划管线（提取→补全→缺项→生成→写回）
│       ├── plugin_registry.py   # 子 Agent 注册中心（discover / AST 元数据 / load_agent）
│       ├── memory.py            # 两层记忆：后端协议（InMemory 兑底 / Postgres 用户隔离）
│       ├── memory_pg.py         # Postgres 后端（psycopg 四表含 users，按会话过滤）
│       ├── auth.py              # 认证（JWT + bcrypt，用户存储 env 分派）
│       ├── rag.py               # 知识问答（向量检索 + Chroma）
│       ├── web.py               # 联网查询（ToolNode + ReAct）
│       ├── stability.py         # 稳定性层（重试/熔断/兜底/健康检查）
│       ├── webapp.py            # FastAPI Web 界面（JWT 认证 + 用户隔离）
│       ├── agents/              # 内置子 Agent 实体（每个 = INTENT + DESCRIPTION + run）
│       │   ├── itinerary_agent.py   # 行程规划（trip_planner 收口）
│       │   ├── preference_agent.py  # 偏好记录（追加/覆盖）
│       │   ├── history_agent.py     # 历史查询（读长期记忆）
│       │   ├── knowledge_agent.py   # 知识问答（rag 向量检索）
│       │   ├── web_agent.py         # 联网查询（含指代消解）
│       │   └── other_agent.py       # 其他（边界兜底）
│       ├── demos/
│       │   ├── plugin_demo.py       # 多 Agent 机制演示（发现/懒加载/热插拔/真实路由）
│       │   └── stability_demo.py    # 稳定性演示（重试/熔断/故障注入/健康检查）
│       └── static/
│           └── index.html           # Web 前端（聊天气泡 + chips，无外部 CDN）
│
├── plugins/                     # 外部扩展子 Agent 目录（注册表自动发现）
│   └── stats.py                 # 差旅统计（第七意图，真实路由）
│
├── tests/                       # 自动化测试（pytest）
│   ├── conftest.py              # 每测试注入全新 InMemoryBackend（零外部依赖）
│   ├── test_memory.py           # 记忆：追加/覆盖/常驻城市/历史
│   ├── test_memory_backend.py   # 后端协议：InMemory 直测 + 会话隔离矩阵 + env 分派
│   ├── test_memory_pg.py        # （Postgres，条件跑）真库读写 + session 隔离
│   ├── test_auth.py             # 认证：bcrypt 哈希 / JWT 签验 / 注册登录 / env 分派
│   ├── test_webapp.py           # webapp 端点：注册/登录/me + 聊天强制用户隔离
│   ├── test_itinerary.py        # 行程：缺失检查 + 结果格式
│   ├── test_plugin.py           # 注册中心：发现/懒加载/内置优先/热插拔
│   ├── test_stability.py        # 熔断三态/重试/兜底
│   ├── test_rag.py              # RAG：分块（单元）+ 检索（集成）
│   ├── test_intent.py           # （集成）意图识别 7 用例含边界
│   ├── test_endtoend.py         # （集成）两层记忆闭环 + 外部扩展派发 + 多意图并行
│   ├── test_graph_builder.py    # 图工厂：图结构/指纹缓存/热插拔（单元）
│   ├── test_llm.py              # LLM 接缝
│   ├── test_scheduler.py        # 调度优化（并行组件，单元）
│   ├── test_session.py          # 会话循环
│   └── test_web.py              # 联网查询
│
├── docs/
│   ├── layer-map.html           # 代码层映射挂图（运行时 + 脚手架动机）
│   ├── adr/                     # 架构决策记录（ADR-0001..0008）
│   ├── documents/               # 知识库语料（8 份政策文档）
│   ├── agents/                  # Agent 技能协作文档
│   └── screenshots/             # 演示截图 6 张
│
├── data/                        # 运行数据（自动生成，gitignored）
│   ├── chroma/                  # 向量索引
│   └── stability.log            # 日志
│
├── docker-compose.yml           # 生产部署：app + postgres（docker compose up -d --build）
├── Dockerfile                   # 生产镜像（Python 3.11 + uv，非 root，健康检查）
├── .dockerignore                # 构建上下文排除（.env/测试/文档不入镜像）
├── .github/
│   └── workflows/ci.yml         # CI：单元层必跑 + 集成层（有 secrets 才跑）+ 镜像构建
│
├── delivery/                    # 交付压缩包输出（gitignored）
└── .scratch/                    # 本地 issue tracker（内部，不进交付包）
```

## 6. 关键设计

### 6.1 结构化输出

DeepSeek 对 `json_schema` 方法支持不稳定，统一用 `json_mode`：

```python
llm = ChatOpenAI(..., extra_body={"thinking": {"type": "disabled"}})
model = prompt | llm.with_structured_output(Schema, method="json_mode")
```

纪律：键名英文写死、JSON 花括号转义、字段形状写死在提示词里。

### 6.2 行程规划

两阶段管线：**要素提取 → 行程生成**。生成时注入用户偏好并输出安排理由；要素缺失时主动索要，不硬生成占位行程。

**“实感”数据层**（确定性、零幻觉）：行程单自动附带 💰 费用估算——内置主流线路**真实高铁车次/二等座票价表**（如北京→杭州 G31 约 553 元/程）、城市分级住宿价（与差旅政策一致：一线 500 / 二线 400 / 三线 300 元/晚）、餐饮标准（午晚餐 100 元/餐），合计出总预算并标注“参考价”。价格全部由代码计算，不让 LLM 编数字。

### 6.3 知识问答

text-embedding-v3 + Chroma 余弦检索 top-5，命中块拼进提示词生成答案，无需查询改写。

### 6.4 两层记忆（用户隔离）

- **短期**：最近 6 轮对话每轮注入，支持指代消解（「那上海呢」→ 问天气）。
- **长期**：偏好（追加/覆盖区分）、常驻城市（自动补出发城市）、历史行程。
- **用户隔离**：webapp 层强制——登录后会话维度 = 用户名（JWT 解出，客户端不自填）；
  链路贯穿 webapp → chat → 图 State → 子 Agent → 存储后端（ADR-0007）。
- **存储后端**：设 `POSTGRES_URL` 走 Postgres（psycopg 四表含 users，持久化 + 隔离）；
  不设则 InMemory 演示兜底（重启即失）。本地起库：`docker compose up -d`。

### 6.5 联网查询

`@tool` → `bind_tools` → `ToolNode` ReAct 循环。免费 API 自动重试 2 次 + 降级文案；内置 20 城经纬度表，未收录城市走 OSM Nominatim 兜底。

### 6.6 调度优化

一句话含多个独立请求时拆分子任务，Send 并行执行（fan-out/fan-in），归约器 `collected` 拼接结果，避免多子 Agent 写同一 key 互相覆盖。**产品默认图即调度图**（session.chat → 图工厂 parallel=True）：Web 界面/命令行/演示全部生效，单意图路径与主管图完全兼容。

### 6.7 多 Agent / 子 Agent 注册机制

`plugin_registry.discover()` 扫描内置 `src/xiao_wen/agents/` + 外部 `plugins/` 目录；AST 渐进式披露（意图识别阶段只读 INTENT/DESCRIPTION 元数据，不执行子 Agent 代码）；`load_agent()` 派发时才加载（懒加载，未使用的子 Agent 不加载）；**图工厂**（graph_builder）由 manifest 动态组装主管/调度图，**指纹缓存自动重建**——新增子 Agent（丢一个文件）→ 下次调用即新图、主管自动认识新意图（运行中热插拔，plugin_demo 第3幕演示；无需 importlib.reload）。内置优先，外部扩展同意图时被忽略。

### 6.8 工程稳定性

六件套：LLM 重试（max_retries + 指数退避）/ 超时控制 / 熔断三态 / `safe_call()` 异常兜底 / 日志 / 健康检查。演示含真实故障注入（坏 key 裸调用崩溃 vs 稳定层优雅降级）。

### 6.9 可视化 Web 界面

FastAPI 复用 `xiao_wen.system` 完整系统零重写，原生 HTML/JS 前端（无外部 CDN）。**Agent 能力可视化**：左侧记忆侧栏实时展示当前账号已记住的偏好与历史行程（`GET /api/memory`）；每条回复带对应子 Agent 徽章（行程规划/偏好记忆/历史查询/知识库/联网查询）；行程规划答案结构化渲染为逐日卡片（交通/住宿/活动/天气提醒），告别纯文本。接口：GET /、POST /api/chat、GET /api/memory、GET /healthz、GET /docs。

## 7. 核心示例（演示三类案例）

### 案例一：行程规划（含偏好记忆闭环）

```text
用户：我不吃辣，住宿喜欢安静
意图：偏好记录
→ ✅ 已新增偏好：餐饮｜不吃辣

用户：10月8日去北京开会4天        （没说出发城市 → 用常驻城市上海）
意图：行程规划
→ 📋 10月8日从上海乘高铁赴北京，入住全季酒店（前门大街店），为期4天会议…
   💡 安排理由：· 高铁往返符合上海至北京的距离 · 考虑你不吃辣的偏好…
   【2026-10-08】交通：高铁 G2 次 07:00 上海虹桥→11:28 北京南
   【2026-10-09】…会议、用餐（清淡不辣）…
   【2026-10-11】返程：高铁 G3 次 16:00 北京南→20:32 上海虹桥
```

### 案例二：偏好记忆 / 历史记忆

```text
用户：我现在常住上海
意图：偏好记录 → ✅ 已更新偏好：常驻城市｜上海（覆盖而非追加）

用户：我上次的行程是什么
意图：历史查询 → 🗂️ 历史行程：· 2026-10-08 上海→北京，4天：…
```

### 案例三：知识问答 + 信息查询

```text
用户：出差住宿标准是什么？
意图：知识问答 → 向量检索命中政策文档：
  一线城市（北上广深）不超过500元/晚；二线不超过400元/晚；三线及以下不超过300元/晚；
  优先连锁品牌酒店，女性员工单独出差选择安全性较高酒店。

用户：北京今天天气怎么样？  → 晴 31.0°C，湿度 49%（实时 API）
用户：那上海呢              → 上海 26.7°C（短期记忆指代消解）
用户：这个暑假去哪里玩      → 正确拒绝：不在企业差旅服务范围（边界）
```

### 案例四：调度优化（多请求并行）

```text
用户：帮我查下出差住宿标准是什么，顺便看看北京今天天气怎么样
意图：知识问答（包含两个请求）
拆分为 2 个子任务（并行执行）：
  · 知识问答｜出差住宿标准是什么
  · 联网查询｜北京今天天气怎么样
⚡ 同时为你处理了 2 个请求：
【知识问答】一线城市不超过500元/晚；二线400；三线300；优先连锁品牌…
【联网查询】北京当前天气：晴 30.5°C
```

## 8. 功能完成情况

| 功能 | 能力要求 | 完成情况 |
|---|---|---|
| A 多 Agent 基本架构 | ≥5 个分工 Agent | ✅ 6 个内置子 Agent（可动态发现实体）+ 外部扩展动态并入，职责边界清晰 |
| B 自然语言意图识别 | LLM 语义识别 + 提取关键信息 | ✅ LLM 动态词汇表路由（json_mode），要素提取做实 |
| C 行程规划主流程 | 识别→抽要素→调子 Agent→生成完整行程 | ✅ 端到端（案例一） |
| D 基础记忆能力 | 可持续记忆，下一轮能引用 | ✅ 偏好+历史+常驻城市（案例二） |
| E 结果可读性 | 摘要/每日安排/理由/注意/缺失提示/来源 | ✅ 行程摘要+每日安排+安排理由+备注；要素缺失主动提示；知识问答标注来源文档 |

## 9. 进阶功能

| 进阶功能 | 状态 | 说明 |
|---|---|---|
| A 两层记忆架构 | ✅ 完整 | 短期（最近 6 轮对话注入）+ 长期（偏好/历史/常驻城市）+ **追加/覆盖区分** |
| B 调度优化 | ✅ 完整 | 按任务类型动态路由 + 多请求 Send 并行执行 + 先收集信息再规划（要素提取） |
| C 插件化、模块化架构 | ✅ 完整 | 子 Agent 注册中心：动态发现（目录扫描）+ 自动扫描注册 + 渐进式披露（AST 元数据，意图识别阶段仅加载元数据）+ 懒加载（未使用模块不加载）+ 热插拔演示 |
| D 工程稳定性 | ✅ 完整 | 六件套：LLM 重试（max_retries+指数退避）/ 超时控制 / 熔断三态 / 异常兜底 / 日志 / 健康检查；含真实故障注入演示（坏 key → 裸调用 401 崩溃 vs 优雅降级） |
| E 评测与测试 | ✅ 完整 | 分层自动化测试 130 个：单元层 115（记忆/行程/注册中心/稳定性/RAG 分块/图工厂/会话隔离/认证/webapp 端点，无 LLM；其中 6 个 Postgres 真库测试需本地容器+`POSTGRES_TEST_URL` 才跑）+ 集成层 15（意图识别 7 用例含边界 + 外部扩展识别 2 + 多意图拆分 2、端到端记忆闭环 + 外部扩展端到端派发 + 多意图并行、向量 RAG 检索）；`uv run pytest` / `-m integration` |
| F 可视化界面 | ✅ 完整 | FastAPI + 原生 JS Web 界面：Agent 徽章 + 记忆侧栏 + 行程卡片结构化渲染，复用 `xiao_wen.system` 完整系统零重写；演示截图 6 张见 docs/screenshots/ |

## 10. 已知问题或后续优化方向

**已知问题（诚实声明）**
- 行程中的车次/航班为模型生成的**参考方案**，非真实预订（演示未接票务系统）。
- 天气/汇率/空气质量来自免费公开 API：① geocoding 子域名曾失效（已换 OSM Nominatim）；② API 不稳定（已加重试+降级，仍可能偶发失败）。
- 演示模式（未设 `POSTGRES_URL`）记忆为进程内存，**重启即失**；持久化需设 `POSTGRES_URL`（本地 `docker compose up -d`）。
- 认证按用户名隔离（JWT，ADR-0007），但**无角色授权**（无 admin/普通用户之分）——多角色需再接授权层。
- 向量检索依赖外部 Embedding API，结果不可解释，复杂语义仍有边界。

**后续优化方向**
- 行程校验层：行程生成后过「RAG 政策校验 + 实时班次/天气合理性检查」（把知识 Agent 与联网 Agent 组合）。
- 记忆精确化：支持「上次住的什么酒店」级细粒度历史查询（当前按行程摘要级别存储）。
- 记忆扩展：短期对话迁移 LangGraph checkpointer（thread 维度随时恢复）、长期记忆语义检索
  （PostgresStore + pgvector）——存储层已收口到 `memory.py` 后端协议，可平滑演进（ADR-0006）。

---

## 项目结构

交付压缩包（一条命令，只含已提交的成品文件，自动排除 `.env`/`data`/未跟踪文档）：
`git archive HEAD README.md .env.example .python-version pyproject.toml uv.lock src tests plugins docs Dockerfile docker-compose.yml .dockerignore .github/workflows/ci.yml --format=zip -o delivery/xiao-wen.zip`

| 目录 | 内容 | 是否进交付包 |
|---|---|---|
| `src/` `tests/` `plugins/` `docs/` | 系统代码（`src/xiao_wen/` 成品包，含 `agents/` 内置子 Agent）+ 测试 + 外部扩展 + 知识库/截图 | ✅ 成品 |
| `README.md` `pyproject.toml` `uv.lock` `.env.example` `.python-version` | 说明 + 依赖锁定 + 环境变量模板 + Python 版本 | ✅ 成品 |
| `Dockerfile` `docker-compose.yml` `.dockerignore` `.github/workflows/ci.yml` | 生产部署（app + postgres 一条命令）+ 镜像构建 + CI | ✅ 成品 |
| `AGENTS.md` `.scratch/` | 本仓库 Agent 协作配置与本地 issue tracker | ❌ 内部 |
