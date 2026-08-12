# 差旅"晓问" —— 智能出行助手 Agent

一个基于 **LangGraph 多 Agent 架构**的企业差旅智能助手：用户用自然语言提出差旅需求，系统通过「意图识别 → 调度 → 专职 Agent 协作」完成**行程规划、偏好记忆、历史查询、政策知识问答、实时信息查询**等任务。

> 演示环境与代码：本仓库即完整项目。核心演示入口：`python homework/0010_system.py`

---

## 1. 项目简介

差旅场景有明确的**多角色分工**特点：识别用户要什么（意图）→ 决定派谁去做（调度）→ 各专职 Agent 分别处理（规划行程 / 记偏好 / 查历史 / 答政策 / 查实时信息）。本项目把这些能力拆成 6 个可独立开发、独立验证、再组装的工作单元（Worker），由一个 LLM 意图主管统一调度，形成「**主管-工人（Supervisor–Workers）**」多 Agent 架构。

设计主线（先桩后实）：**先搭骨架验证流程，再逐个把 Worker 做实**。每一课的演进都独立留档（见 `teaching/learning-records/`），最终系统 6 个 Worker 全部做实，基础项 A–E 全部完成。

## 2. 技术栈

| 类别 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.11 | Agent 开发主流语言 |
| 编排框架 | LangGraph 1.2.10 | 状态图（StateGraph）、条件边、ToolNode、ReAct 循环 |
| LLM 框架 | LangChain / langchain-openai 1.4.2 | ChatOpenAI、结构化输出、@tool |
| 大模型 | DeepSeek（OpenAI 兼容接口） | 意图识别、要素提取、行程生成、问答、工具调用 |
| Embedding | 阿里 DashScope text-embedding-v3（1024 维） | 知识库向量化 |
| 向量库 | Chroma 1.5.9（磁盘持久化） | 政策文档语义检索 |
| 关键词检索 | jieba 分词 + BM25 | 检索效果对照实验（第七课） |
| 记忆存储 | 本地 JSON 文件（`data/memory.json`） | 短期对话 + 长期偏好/历史（分层设计，见 §6.4） |
| 联网数据 | open-meteo（天气/空气质量）、exchangerate-api（汇率） | 免费公开 API，无需 key |
| 包管理 | uv | 依赖锁定（pyproject.toml + uv.lock） |
| 类型检查 | mypy（dev 依赖） | 全项目 0 警告（22→0），见 §6.8 |
| 插件机制 | 自研插件注册中心 | 动态发现/懒加载/渐进式披露（加分项 C），见 §6.9 |
| 稳定性层 | 自研 + LangChain 内置 | 重试/超时/熔断/兑底/日志/健康检查（加分项 D），见 §6.10 |
| 测试框架 | pytest 9 + pytest.mark | 分层测试 41 个：单元 32（无 LLM）+ 集成 9（真实模型），见 §6.11 |

## 3. 系统架构

```
                          ┌─────────────────────────────┐
                          │   用户输入（自然语言）         │
                          └──────────────┬──────────────┘
                                         ▼
                          ┌─────────────────────────────┐
                          │  Intention Agent 意图识别     │
                          │  （LLM 六分类 + json_mode）    │
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

意图六分类：`行程规划 / 偏好记录 / 历史查询 / 知识问答 / 联网查询 / 其他`（兜底边界）。产品边界规则：**仅服务企业差旅**，个人休闲旅游等一律归「其他」。

## 4. Agent 列表与职责说明

作业要求的 8 个角色在本系统中的落地：

| 作业角色 | 系统实现 | 职责 | 关键技术 |
|---|---|---|---|
| Intention Agent 意图识别 | `classify_intent` 节点 | 六分类 + 理由 | LLM + json_mode 结构化输出 |
| Orchestration Agent 调度 | 条件边路由 | 按意图把请求分派给对应 Worker | `add_conditional_edges` |
| Event Collection Agent 要素提取 | 行程 Worker 第一阶段 | 提取出发/目的/日期/时长/偏好 | LLM 结构化输出 |
| Preference Agent 偏好 | `preference` 节点 | 偏好写入（追加/覆盖区分） | 长期记忆 |
| Memory Query Agent 记忆查询 | `history` 节点 | 返回历史行程 | 长期记忆 |
| Knowledge/RAG Agent 知识问答 | `knowledge` 节点 | 政策库语义检索 + 生成 | embedding + Chroma |
| Information Query Agent 联网查询 | `web` 节点 | 天气/汇率/空气质量 | ToolNode + ReAct 循环 |
| Itinerary Planning Agent 行程规划 | `itinerary` 节点 | 生成完整行程 | 两阶段管线 + 偏好注入 |

## 5. 运行方式说明

```bash
# 1) 安装依赖（uv 管理）
uv sync

# 2) 配置 .env（项目根目录）
#    DEEPSEEK_API_KEY=你的Key        （OpenAI 兼容中转或官方）
#    DEEPSEEK_BASE_URL=https://...   （模型服务地址）
#    DEEPSEEK_MODEL=deepseek-v4-flash
#    DASHSCOPE_API_KEY=你的Key        （阿里云百炼，用于 text-embedding-v3）

# 3) 一键体验完整系统（推荐）
python homework/0010_system.py

# 4) 分模块验证各 Agent（每课独立测试）
python homework/0003_intent.py     # 意图识别
python homework/0004_scheduler.py  # 调度路由
python homework/0005_itinerary.py  # 行程规划 Worker
python homework/0006_memory.py     # 记忆闭环
python homework/0007_rag.py        # 知识问答（BM25 关键词版）
python homework/0008_rag_vector.py # 知识问答（向量检索升级版）
python homework/0009_web.py        # 联网查询（工具调用）
python homework/0011_scheduler.py  # 调度优化：多请求并行执行
python homework/0012_plugin.py     # 插件化架构：动态发现/懒加载/热插拔（四幕演示）
python homework/0013_stability.py  # 工程稳定性：重试/熔断/故障注入/健康检查（四幕演示）
uv run pytest                  # 自动化测试：单元层 26 个（无 LLM，秒级）
uv run pytest -m integration   # 自动化测试：集成层 8 个（真实 LLM，约 1 分钟）
uv run python homework/0014_webapp.py    # 可视化 Web 界面（加分项 F）→ http://127.0.0.1:8000
uv run python scripts/screenshot_demo.py # 无头浏览器生成演示截图 → docs/screenshots/
uv run python scripts/delivery.py all   # 交付三连：门禁(pytest+mypy+冒烟) → 打包 → 邮件模板
```

> 首次运行 `0010_system.py` 中知识问答会构建向量索引（一次性，约 386 个文本块），之后复用磁盘索引，秒级返回。

### 目录结构

```
homework/
  0003_intent.py        意图识别（LLM 六分类）
  0004_scheduler.py     调度器骨架（条件边路由）
  0005_itinerary.py     行程规划 Worker（要素提取→行程生成）
  0006_memory.py        记忆闭环（偏好/历史/行程读偏好）
  0007_rag.py           知识问答 v1（BM25 关键词检索）
  0008_rag_vector.py    知识问答 v2（向量检索 + Chroma）
  0009_web.py           联网查询（ToolNode + ReAct）
  0010_system.py        ★ 完整系统（6 Worker 全做实）
  0011_scheduler.py     ★ 调度优化（Send 并行执行，复用 0010 worker）
  0012_plugin.py        ★ 插件化演示（插件式主管 + 四幕：发现/懒加载/热插拔/边界）
  0013_stability.py     ★ 稳定性演示（重试/熔断/真实故障注入/健康检查）
  0014_webapp.py        ★ 可视化 Web 界面（FastAPI 后端，复用 0010 完整系统）
  plugin_registry.py    插件注册中心（discover / AST 元数据 / load_plugin）
  stability.py          稳定性层（with_retry / CircuitBreaker / safe_call / health_check）
  static/index.html     Web 前端（聊天气泡 + 建议 chips + 打字机，无外部 CDN）

scripts/                工具脚本
  screenshot_demo.py     无头浏览器演示截图 → docs/screenshots/

docs/screenshots/        演示截图 6 张（作业 8.1 提交材料：首页/行程/天气/指代消解/知识问答/历史）

tests/                  自动化测试（加分项 E，pytest）
  conftest.py           记忆隔离到 tmp_path（绝不碰真实数据）
  test_memory.py        记忆：追加/覆盖/常驻城市/历史/常用目的地
  test_itinerary.py     缺失检查 + 结果可读性格式
  test_plugin.py        插件注册中心（含「加载即爆炸」零执行验证）
  test_stability.py     熔断三态/重试/兑底
  test_rag.py           RAG 验证：分块管线/BM25 检索（单元）+ 向量检索（集成）
  test_intent.py        （集成）意图识别 7 用例含边界
  test_endtoend.py      （集成）两层记忆闭环
  memory_store.py       记忆存储层（短期 + 长期，可替换实现）

plugins/                插件目录（每个插件 = INTENT + DESCRIPTION + run()）
  policy.py             插件：知识问答（复用 0008 向量 RAG）
  weather.py            插件：联网查询（复用 0009 天气工具）
  stats.py              插件：差旅统计（新功能，演示动态发现）
data/memory.json        记忆数据（自动生成，已 gitignore）
data/chroma/            向量索引（自动生成，已 gitignore）
```

## 6. 关键设计说明

### 6.1 结构化输出方案（踩坑实证）

DeepSeek 模型对 `json_schema` 方法支持不稳定（能力矩阵实测），最终统一方案：

```python
llm = ChatOpenAI(..., extra_body={"thinking": {"type": "disabled"}})
model = prompt | llm.with_structured_output(Schema, method="json_mode")
```

配套三条纪律：**键名英文写死、JSON 花括号转义、字段形状在提示词里钉死**。教训：结构化输出「上下文一变就要重新验证」（第七课 RAG 时结构漂移过）。

### 6.2 行程规划：两阶段管线 + 质量保障

行程 Worker 内部分两阶段：**要素提取 → 行程生成**。生成阶段注入用户历史偏好（记忆），并输出**安排理由**（政策约束/偏好/交通合理性）。输入要素不全时（缺城市/日期/天数）主动向用户索要，不硬生成占位行程。

### 6.3 知识问答：关键词 → 向量检索的升级（对照实验）

| | v1（第七课） | v2（第八课） |
|---|---|---|
| 检索 | jieba 分词 + BM25 | text-embedding-v3 + Chroma 余弦 top-5 |
| 查询改写 | 需要（改写后才命中） | 不需要 |
| 语义案例 | 「延长出差时间」误命中环保文档（"长时间"词面匹配） | 一次命中 FAQ |
| 依赖 | 无 | Embedding API + 向量库 |

升级动机是**对照实验**：关键词版暴露语义天花板后，换成向量检索解决。诚实说明：向量检索依赖外部 API 且不可解释，真实产品做关键词+向量混合检索。

### 6.4 两层记忆（加分项 A）

对应 LangChain 官方 Memory 概念：

- **短期记忆（thread-scoped）**：最近 6 轮对话，每轮推理前注入 → 支持指代消解（「那上海呢」→ 理解是问天气）。注入克制截断，避免长历史塞满上下文（hot path 权衡）。
- **长期记忆（跨会话）**：偏好（**追加/覆盖区分**：is_update 时替换同类别旧条目）、常驻城市（行程规划自动补出发城市）、历史行程、常用目的地。
- 官方对应：短期=checkpointer+thread，长期=store。本项目用 JSON 文件演示分层概念，真实产品短期换 Redis/长期换 MySQL（§9）。

### 6.5 联网查询：工具调用 + 重试降级

`@tool`（docstring 即 LLM 说明书）→ `bind_tools` → `ToolNode` → 条件边 ReAct 循环。能力矩阵实证：本模型**只支持 auto 模式**（强制 tool_choice 不可用），负例能正确拒绝调用工具。网络层：统一 `requests`、读取环境变量代理、自动重试 2 次 + 降级错误文案（免费 API 不稳定，实测多次）。Web 联调时发现 nominatim 地理编码不可用 → 内置 20 城经纬度表（零依赖永远可用）+ nominatim 兑底（未收录城市才走外部 API），多级降级「能本地化的绝不依赖网络」。

### 6.6 工程组装：先桩后实 + 模块化

第六课先搭「主管 + 6 Worker 桩」骨架，之后逐个做实（行程→记忆→知识→联网），第十课总装只做「导入 + 挂图」，拓扑零改动。Worker 间统一「输入 state → 输出 answer」接口契约。

### 6.7 调度优化：多请求并行执行（加分项 B）

一句话含多个独立请求时（「查下住宿标准，顺便看看北京天气」），意图识别拆分子任务（subtasks），条件边函数返回 **Send 列表**（LangGraph fan-out 并行），各并行 Worker 完成后 fan-in 到 merge 汇总。并行结果用归约器字段 `collected` 拼接，避免多 Worker 写同一 key 互相覆盖。单意图路径不变（拆不出时回退原路由）。

### 6.8 工程质量：类型检查（mypy）

`uv run mypy homework/` → 0 警告。22 个警告分三类处理：真 Bug（0006 曾 import 已改名的 `add_preference`，一跑就 ImportError——改名后必须全局搜引用+回归）；防御性改进（`raise RuntimeError(...) from last`、importlib spec None 检查、结构化输出断言收窄为模型实例）；库噪音（LangGraph invoke 重载对部分键 State 输入过严 → 配置级关闭 call-overload 并注明理由）。

### 6.9 插件化架构（加分项 C）

子 Agent 支持动态发现机制：① 自动扫描注册——`discover()` 扫描 `plugins/` 目录，每个插件声明 `INTENT + DESCRIPTION + run(query)->str`；② 渐进式披露——意图识别阶段用 **AST 解析**只读插件元数据（不执行模块代码）；③ 懒加载——派发时才 `exec_module` + 缓存。演示四幕：发现（零加载）→ 懒加载（哨兵日志）→ **热插拔**（运行中新增插件，主管自动认识新意图，零代码改动）→ 边界。动态性的代价：意图类别从静态 `Literal` 变为运行时校验。

### 6.10 工程稳定性（加分项 D）

六件套：① LLM 重试——ChatOpenAI `max_retries=2`（内置）+ 自定义 `with_retry` 指数退避；② 超时控制——`timeout=30`；③ 熔断——`CircuitBreaker` 三态（closed→open→half_open），连续失败 3 次打开、恢复期半开试探，后续请求零耗时快速失败；④ 异常兑底——`safe_call()` 任何异常返回友好降级文案，系统不崩；⑤ 日志——logging 双写 stdout + `data/stability.log`；⑥ 健康检查——`health_check()` 自检 .env/向量索引/记忆/插件/日志五项。演示含**真实故障注入**：坏 API key 下裸调用 401 崩溃 vs 稳定性层 281ms 优雅降级。

### 6.11 评测与测试（加分项 E）

分层测试（pytest 9）：单元层 32 个无 LLM（记忆读写/追加覆盖、行程缺失检查/结果格式、插件注册中心、熔断/重试/兑底、**RAG 分块管线与 BM25 检索质量**）秒级离线可跑；集成层 9 个真实模型（意图识别 7 用例含边界、端到端两层记忆闭环、**向量 RAG 真实 embedding 检索相关性**）用 `-m integration` 显式跑。关键做法：conftest 记忆隔离到 tmp_path（不碰真实数据）、参数化用例表、**「加载即爆炸」假插件实证 AST 渐进披露零执行**、**RAG 双版本验证（0007 BM25 纯本地 + 0008 向量真实 embedding）对照关键词检索与语义检索**。

### 6.12 可视化 Web 界面（加分项 F）

FastAPI + uvicorn 后端复用 0010 完整系统（Agent 逻辑零重写），原生 HTML/JS 前端（聊天气泡 + 建议 chips + 打字机效果 + XSS 转义，无外部 CDN 离线可用）。接口：GET /（页面）、POST /api/chat（走完整主管图 + 两层记忆闭环）、GET /healthz（配合加分项 D）、GET /docs（自动文档）。Web 联调时发现 nominatim 地理编码服务不可用 → 内置 20 城经纬度表（零依赖永远可用）+ nominatim 兑底，多级降级。演示截图 6 张（playwright 无头浏览器，真实运行）见 docs/screenshots/。

## 7. 核心示例（演示三类案例）

### 案例一：行程规划（含偏好记忆闭环）

```
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

```
用户：我现在常住上海
意图：偏好记录 → ✅ 已更新偏好：常驻城市｜上海（覆盖而非追加）

用户：我上次的行程是什么
意图：历史查询 → 🗂️ 历史行程：· 2026-10-08 上海→北京，4天：…
```

### 案例三：知识问答 + 信息查询

```
用户：出差住宿标准是什么？
意图：知识问答 → 向量检索命中政策文档：
  一线城市（北上广深）不超过500元/晚；二线不超过400元/晚；三线及以下不超过300元/晚；
  优先连锁品牌酒店，女性员工单独出差选择安全性较高酒店。

用户：北京今天天气怎么样？  → 晴 31.0°C，湿度 49%（实时 API）
用户：那上海呢              → 上海 26.7°C（短期记忆指代消解）
用户：这个暑假去哪里玩      → 正确拒绝：不在企业差旅服务范围（边界）
```

### 案例四：调度优化（多请求并行）

```
用户：帮我查下出差住宿标准是什么，顺便看看北京今天天气怎么样
意图：知识问答（包含两个请求）
拆分为 2 个子任务（并行执行）：
  · 知识问答｜出差住宿标准是什么
  · 联网查询｜北京今天天气怎么样
⚡ 同时为你处理了 2 个请求：
【知识问答】一线城市不超过500元/晚；二线400；三线300；优先连锁品牌…
【联网查询】北京当前天气：晴 30.5°C
```

## 8. 已完成基础项

| 基础项 | 要求 | 完成情况 |
|---|---|---|
| A 多 Agent 基本架构 | ≥5 个分工 Agent | ✅ 6 个 Worker（§4 表），职责边界清晰 |
| B 自然语言意图识别 | LLM 语义识别 + 提取关键信息 | ✅ LLM 六分类路由（json_mode），要素提取做实 |
| C 行程规划主流程 | 识别→抽要素→调子 Agent→生成完整行程 | ✅ 端到端（案例一） |
| D 基础记忆能力 | 可持续记忆，下一轮能引用 | ✅ 偏好+历史+常驻城市（案例二） |
| E 结果可读性 | 摘要/每日安排/理由/注意/缺失提示/来源 | ✅ 行程摘要+每日安排+安排理由+备注；要素缺失主动提示；知识问答标注来源文档 |

## 9. 已完成加分项

| 加分项 | 状态 | 说明 |
|---|---|---|
| A 两层记忆架构 | ✅ 完整 | 短期（最近 6 轮对话注入）+ 长期（偏好/历史/常驻城市）+ **追加/覆盖区分** |
| B 调度优化 | ✅ 完整 | 按任务类型动态路由 + 多请求 Send 并行执行 + 先收集信息再规划（要素提取） |
| C 插件化、模块化架构 | ✅ 完整 | 插件注册中心：动态发现（目录扫描）+ 渐进式披露（AST 元数据）+ 懒加载 + 热插拔演示 |
| D 工程稳定性 | ✅ 完整 | 六件套：LLM 重试（max_retries+指数退避）/ 超时控制 / 熔断三态 / 异常兜底 / 日志 / 健康检查；含真实故障注入演示（坏 key → 裸调用 401 崩溃 vs 优雅降级） |
| E 评测与测试 | ✅ 完整 | 分层自动化测试 41 个：单元层 32（记忆/行程/插件/稳定性/RAG 分块与 BM25，无 LLM）+ 集成层 9（意图识别 7 用例含边界、端到端记忆闭环、向量 RAG 检索）；`uv run pytest` / `-m integration` |
| F 可视化界面 | ✅ 完整 | FastAPI + 原生 JS Web 界面（聊天气泡/chips/打字机），复用 0010 完整系统零重写；演示截图 6 张见 docs/screenshots/ |

## 10. 已知问题或后续优化方向

**已知问题（诚实声明）**
- 行程中的车次/航班为模型生成的**参考方案**，非真实预订（作业演示未接票务系统）。
- 天气/汇率/空气质量来自免费公开 API：① geocoding 子域名曾失效（已换 OSM Nominatim）；② API 不稳定（已加重试+降级，仍可能偶发失败）。
- 记忆为单用户 JSON 文件存储：无多用户隔离、无并发控制（演示够用，生产不适用）。
- 向量检索依赖外部 Embedding API，且结果不可解释；「延长出差时间」类语义问题已验证优于关键词版，但仍有边界。

**后续优化方向**
- 行程校验层：行程生成后过「RAG 政策校验 + 实时班次/天气合理性检查」（把知识 Agent 与联网 Agent 组合）。
- 调度优化：优先级调度、同优先级并行执行、收集信息后再触发规划。
- 记忆精确化：支持「上次住的什么酒店」级细粒度历史查询（当前按行程摘要级别存储）。
- 存储升级：短期换 Redis（TTL）、长期换 MySQL/PostgreSQL、检索换 Milvus/Qdrant——存储层已集中到 `memory_store.py`，可平替。
- 可视化：Web 界面（Gradio/Streamlit）交互。

---

*教学项目 · 设计演进全程记录见 `teaching/learning-records/`（LR-0001 ~ LR-0019）*

## 项目结构：成品 vs 教学过程

仓库顶层刻意区分两类内容，交付压缩包（`python scripts/delivery.py package`）**只含成品**：

| 目录 | 内容 | 是否进交付包 |
|---|---|---|
| `homework/` `tests/` `plugins/` `scripts/` `docs/` | 系统代码 + 测试 + 插件 + 工具 + 知识库/截图 | ✅ 成品 |
| `README.md` `pyproject.toml` `uv.lock` | 说明 + 依赖锁定 | ✅ 成品 |
| `teaching/` | 17 课课件、19 条学习记录、术语表、速查表、教学笔记 | ❌ 教学过程 |
| `AGENTS.md` `.scratch/` | 本仓库 Agent 协作配置与本地 issue tracker | ❌ 内部 |
