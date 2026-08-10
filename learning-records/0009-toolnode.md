# LR-0009 · 联网查询 worker（ToolNode + ReAct 循环）

**日期**：2026-08-10（第八课后）
**主题**：最后一个基础项 worker——联网查询，用 LangGraph ToolNode 接真实天气/汇率 API
**背景**：作业基础项 5 Agent（意图识别/调度/要素提取/知识RAG/行程规划）已齐，联网查询为第 6 个基础项，做满即基础项全覆盖

## 关键决策与事实

1. **数据源选型**：全部用**免费无需 key** 的公开 API——天气 open-meteo（geocoding + forecast，支持中文城市名）、汇率 open.er-api.com。真实产品用付费聚合服务，作业演示免费方案并诚实注明
2. **工具设计**：两个工具 get_weather / get_currency_rate，展示「LLM 自主选择调哪个工具」
3. **机制**：@tool（docstring=LLM 说明书）→ bind_tools 挂载 → ToolNode 执行 → 条件边 ReAct 循环（有 tool_calls → tools；否则 END）
4. **能力矩阵再次实证**：v4-flash tools+auto ✅（LR-0004 结论复用：不要用强制 tool_choice）

## 实测（4/4）

| 提问 | LLM 行为 | 结果 |
|---|---|---|
| 北京今天天气？ | get_weather('北京') | ✅ 晴 33.1°C 湿度 42% |
| 1 美元多少人民币？ | get_currency_rate(USD, CNY) | ✅ 1 USD = 6.75 CNY |
| 东京天气适合穿什么 | get_weather('东京') | ✅ 雷暴 26.1°C 湿度 94%（中文→经纬度自动处理） |
| 报销时限（负例） | 不调工具 | ✅ 正确拒绝：非实时信息 |

负例价值：证明条件边路由正确——LLM 判断「不需要工具」→ END，且明确告知用户属于政策类问题（体现 worker 边界意识）。

## 追加：urllib→requests 的真实病因（用户报 SSL UNEXPECTED_EOF_WHILE_READING）

换 requests 后同错 → 诊断网络：直连国外站点被掐（curl 000）、pateway/pypi 直连可达 → 发现环境有 Clash 代理（127.0.0.1:7897）→ 逐域名验证：
- **geocoding-api.open-meteo.com 子域名废了**（代理下也 SSL EOF）→ 换 OSM Nominatim（免费、需 User-Agent）
- **open.er-api.com 废了** → 换 api.exchangerate-api.com（v4/latest/USD 全量表交叉换算，支持任意币种对）
- **api.exchangerate-api.com 也不稳定**（一次 200 一次 EOF）→ 免费 API 抖动实锤 → 加 _get_json() 重试 2 次 + 降级错误文案
- 工程化：_proxies() 从环境变量读代理（无代理自动直连）

**学生代码审查**（动手任务 get_air_quality 自己写的）：
- ✅ 思路对：docstring、try-except、字段名正确
- ❌ 坑1：库不一致（文件已换 requests，工具还在用 urllib）→ 教训：改库要全局一致
- ❌ 坑2：API 职责混用（geocoding 参数 name/count 用在 air-quality 域名上）→ 教训：先读 API 文档再写，地理编码和数据接口职责分开

**意外教学点**：LLM 回答「北京天气」时**并行调用 get_weather + get_air_quality 两个工具**（ToolNode 支持并行工具调用）——好素材，写进课程

## 学生表现
- 未贴第八课任务输出即「继续」（符合一贯节奏，不阻塞）
- **独立完成动手任务**：自己写了 get_air_quality 工具并加入了 tools 列表（首次自写工具，思路正确，只有两处可教错误）
- 作业基础项进度：意图识别/调度/要素提取/知识RAG/行程规划/联网查询 **6 项全齐** ✅

## 下一步
- 第十课：**组装完整系统 v3**——把 knowledge（0007/0008）、web（0009）、itinerary（0005）、memory（0006）全部接入调度器图（0004），三类演示案例端到端跑通
- 用户任务待收：第八课语义题输出、第九课新工具（空气质量）代码
- 课程后段：加分项（行程校验层 RAG+ToolNode 实时班次）视时间
