# NOTES.md — 教学笔记

## 用户偏好
- **语言**：中文授课、中文材料（2026-08-09 明确要求"说汉语"）
- **目标**：核心是学会设计多 Agent 系统（mission b），作业是练习场
- **基础**：新接触 LLM 多 Agent；有调用 LLM API 的经验，有可用 key
- **Python / LangChain 水平**：未明确——第一课先假设会用 Python、没用过 LangGraph，视作业进展调整
- **风格**：回复偏简短，喜欢直接给结论 + 可一句答完的问题
- **范围外**：模型微调、生产部署（其他未指定）

## 工作区状态
- 2026-08-09 初始化：MISSION.md / RESOURCES.md 已建，第一课完成
- 作业文档：docs/差旅"晓问"——智能出行助手Agent.md（全文 8 个角色，见下）
- docs/homework/character.md 目前是空文件，用户提到它「提供了 8 个角色」——等用户粘贴内容后再读
- 知识库文档：docs/documents/*.txt（8 份企业差旅标准文档，RAG 素材）

## 作业要点（来自 docs/差旅"晓问" 全文）
- **8 个角色**：意图识别、调度、要素提取、偏好、记忆查询、知识/RAG、联网查询、行程规划
- **基础项最低 5 个 Agent**：意图识别 + 调度 + 要素提取 + 知识/RAG + 行程规划（行程规划也在最低建议里！）
- 基础项：多 Agent 架构 / 语义意图识别 / 行程规划主流程 / 基础记忆 / 结果可读性
- 加分项：两层记忆、并行调度、插件化、稳定性、测试、可视化
- 提交：代码压缩包 + README + 演示截图/录屏；演示至少 3 类案例（行程规划、偏好/历史记忆、知识问答或信息查询）
- 推荐技术栈：Python + LangChain + LangGraph（与仓库一致）
- 推荐推进顺序：单轮行程规划主链路 → 意图识别与多 Agent 调度 → 记忆 → 知识问答/信息查询 → 加分项

## 待办 / 观察
- 截止：作业文档写 2026-08-25（用户先说 23 号，按文档算，约两周+）→ 节奏：设计判断力 → LangGraph 实操 → 收尾作业
- 留意用户在 quiz 和练习中的表现，记录到 learning-records/
- 用户提到 docs/homework/character.md 会提供角色详情——拿到后更新教学素材
- 2026-08-09：第一课练习已完成并记录（LR-0001）；第二课（LangGraph 五件套）已交付，含实测代码；等用户交回条件边动手任务
- 用户的 API key 提供商未确认（有调用经验）——下节课接 LLM 前需要问清楚（OpenAI/DeepSeek/豆包等，以及模型名）
- 已确认：中转站接 DeepSeek；已装 langchain-openai + python-dotenv；.env 已建骨架并加入 .gitignore（安全）；课程 0003 已更新为 dotenv 加载方式
- 2026-08-10：0003_intent.py 端到端跑通 3/3（行程规划/知识问答/偏好记录）；系统提示词修复误分类；SecretStr 修复 Pylance 警告；LR-0003 已记
- 2026-08-10：用户手动测试发现间歇 400 → 7 项对照实验锁定根因（deepseek-v4-flash + thinking 模式限制 json_schema/强制 tool_choice）；最终方案 extra_body 关 thinking + method=json_mode + 提示词写死键名；已固化进 homework/0003_intent.py；LR-0004 已记
- 下一课：意图识别接条件边 → 调度骨架（第四课）；条件：中转站 JSON 能力边界已摸清，可直接进多节点图
- 2026-08-10：第四课已交付（调度骨架）：homework/0004_scheduler.py 六类意图 6/6 路由正确（真实 API）；课程 0004 已写；术语表新增「桩（Stub）」；等用户加自己的测试句
- 第五课预告：把「行程规划」工人做实（基础项 A 核心）——先做纯代码版（带偏好/约束的简单规划器），再做 LLM 版；可能接 ToolNode
- 2026-08-10：第五课已交付：homework/0005_itinerary.py 两阶段管线（要素提取→行程生成）实测通过，两段行程质量好；课程 0005 已写；术语表新增「要素提取」；等用户跑自己的测试句
- 第六课预告：记忆（基础项）——偏好记录落库 + 历史查询，可能用简单文件/内存存储，再接行程规划读取偏好
- 2026-08-10：第六课已交付：homework/0006_memory.py 记忆闭环实测通过（偏好落库→行程读偏好用全季→行程写回→历史可查）；课程 0006 已写；术语表新增「记忆」「结构漂移」；data/memory.json 已进 gitignore；等用户跑自己的闭环
- 第七课预告：知识问答（RAG，基础项）——docs/documents/*.txt 8 份企业差旅文档 → 向量检索 + 生成
- 2026-08-10：第七课已交付：homework/0007_rag.py 实测 4/4 通过（住宿标准→一线500/二线400/三线300；报销时限→30自然日+一周内；紧急联系→24h客服999-800-8888+外交部12308；带家属→不可以）。4 轮调试教学点：TF→BM25、标题块与内容合并（chunking）、停用词字符集bug+来源去重、查询改写（中转站不支持 embedding，改关键词检索+LLM 改写）；术语表新增「分块」「BM25」「查询改写」；jieba 已装；等用户跑自己的问题
- 第八课预告：联网查询（ToolNode，基础项）——查天气/实时信息，接 ToolNode；然后各课成果组装成完整系统 v3（把 knowledge worker 接进调度器）
- 2026-08-10：第八课（向量升级）已交付：homework/0008_rag_vector.py（阿里 text-embedding-v3 + chromadb，6/6 全对，语义题「延长出差时间」一次命中 vs 关键词版误命中）；LR-0008 已写；术语表新增「向量检索」「向量数据库」「embedding」；包管理 uv 规范化（uv add dashscope/numpy/chromadb 等，pyproject.toml 6 依赖完整）；key 已配 DASHSCOPE_API_KEY；数据目录 gitignore 已含 data/chroma/ + embeddings.npy；等用户跑对比任务
- 第九课预告：联网查询（ToolNode）——查天气/航班等实时信息；然后组装完整系统 v3（全部工人做实 + knowledge 接入调度器）
- 2026-08-10：第九课已交付：homework/0009_web.py（open-meteo 天气 + er-api 汇率，免费无 key；ToolNode + ReAct 循环 4/4 全对，负例正确拒绝）；LR-0009 已写；术语表新增「工具调用」；基础项 6 项全齐（意图/调度/要素提取/知识RAG/行程/联网）
- 2026-08-10：第十课已交付：homework/0010_system.py（六 worker 全做实：knowledge 接 0008 向量 RAG、web 接 0009 ToolNode 图，importlib 模块化总装）；端到端 6/6 全通，记忆闭环实证（不吃辣偏好渗透进行程每餐）；LR-0010 已写；lesson 0010 已开；术语表新增「总装」
- 2026-08-10：基础项 E 补齐（用户问「ABCDE 都实现了吗」→ 核对发现 E 两处缺口 → 补上）：行程 worker 加缺失信息提示（_missing 检查：日期待定/城市缺/天数缺 → 问用户不硬生成）+ 生成加安排理由（reasons 字段 + 💡 展示）；0005/0006/0010 三处同步；验证 3 例全过（缺 4 项列出/只提示缺 3 项不误报/完整行程带 5 条理由）；**基础项 A-E 全绿**
- 2026-08-10：第十一课已交付（用户主动提出「完善 memory 短期和长期」+ 给官方文档链接）：memory_store 升级两层记忆（短期=messages 最近 6 轮注入；长期=偏好新增/覆盖 is_update + 常驻城市 + 常用目的地）；0010 行程 worker 出发城市缺失自动用常驻城市；demo 改多轮循环；实测 7/7（含「那上海呢」指代消解、覆盖更新）；加分项 A 完成；LR-0011 已写；lesson 0011 已开
- 2026-08-10：第十二课已交付：README.md 初稿完成（对照作业 8.2 十项清单：简介/技术栈/架构/Agent职责/运行方式/关键设计/核心示例/基础项/加分项/已知问题）；加分项如实标注（A✅ BCDE◐ F✖）；诚实声明 4 条；存储选型问答落点为 §9/§10 扩展性说明；uv add requests 补依赖清单；LR-0012 已写
- 2026-08-10：第十二课已交付（用户选「先调度优化」）：homework/0011_scheduler.py 并行调度（Send API fan-out/fan-in）；意图识别加 subtasks 多意图拆分；collected 归约器解决并行写冲突；实测 4/4（单意图回归 + 双意图并行×2 + 边界）；**加分项 B 完成**（动态路由+并行+先收集信息）；README 已更新（§5 目录/§6.7/案例四/加分项 B ✅）；LR-0013 已写；lesson 0012 已开；术语表待补「Send/并行调度」
- 2026-08-10：第十三课已交付（用户选「类型检查警告优化」）：uv add --dev mypy + pyproject 配置；22 警告→0（真 Bug×1：0006 import 已改名的 add_preference 导致 ImportError；防御改进×4；变量注解×6；库噪音 call-overload 配置级关闭+jieba 单处 ignore）；0006 修复后回归、0010/0011 回归全绿；README §2/§6.8/§9 已更新；LR-0014 已写；lesson 0013 已开
- 2026-08-10：第十三课补充（用户追问「不必要的 type ignore 去掉了没」）：21 处 ignore 清理→仅剩 1 处（jieba import-untyped，必要且带理由）；全部用真实代码替代——assert isinstance 收窄结构化输出（0003/0004/0005/0006/0010/0011）、_load 加 spec None 检查（0010 同步 0011）、常驻城市 hc 变量收窄 Optional；mypy 仍 0 警告；回归全绿（0005/0003 冒烟、0010 全量 7 用例、0011 并行）
- 2026-08-10：第十四课已交付（用户问「加分项 C 可行吗」→ 详细讲方案 → 先提交 git ba6ad56 再动手）：plugins/ 三插件（policy/weather/stats）+ homework/plugin_registry.py（discover/AST 元数据/load_plugin）+ 0012_plugin.py（插件式主管四幕演示）；热插拔演示成功（运行中新增插件主管自动认识新意图）；踩坑：@tool 后取 .func、return 换行拼接需括号；mypy homework+plugins 16 文件 0 错误；**加分项 C 完成**；README §2/§6.9/目录/§9 已更新；LR-0015 已写；lesson 0014 已开；术语表补「插件化」；插件化成果待 git 提交
- 2026-08-10：第十五课已交付（用户选「继续 D」→ 精读要求六项 → 实现稳定性层）：homework/stability.py（with_retry 指数退避 / CircuitBreaker 三态 / safe_call 兑底 / logger 双写 / health_check 五项）+ 0013_stability.py 四幕（重试 / 熔断 / 真实故障注入坏 key→401 裸崩 vs 281ms 降级 / 健康检查全 ✅）；0010/0011/0012 llm 加 max_retries=2 + timeout=30（0011 importlib 复用 0010 自动继承）；发现：模型链构造时捕获 llm，monkeypatch 无效→稳定性层必须包调用点；mypy 18 文件 0 错误；0010 回归全绿；**加分项 D 完成**；README §2/§6.10/目录/§9 D→✅；LR-0016 + lesson 0015 已开；术语表补熔断/重试/超时/健康检查；待 git 提交
- 2026-08-10：第十六课已交付（用户问「E测试怎么搞」→ 网络恢复后继续）：uv add --dev pytest；pyproject pytest 配置（testpaths/markers）；tests/ 七文件——conftest（记忆隔离 tmp_path）、test_memory 5 / test_itinerary 5 / test_plugin 4（含「加载即爆炸」AST 零执行验证）/ test_stability 6、集成 test_intent 7 用例含边界 + test_endtoend 记忆闭环；踩坑 3 个（TripRequest 必填字段 hotel_pref/budget_pref、add_or_update_preference 返回无 is_update 键、CircuitBreaker.is_open 惰性迁移）；实测单元 26 + 集成 8 全绿；**加分项 E 完成**；README §2/§6.11/目录 tests/§9 E→✅；LR-0017 + lesson 0016 已开；术语表补单元/集成/参数化/数据隔离；待 git 提交
- 加分项全景：A ✅ 两层记忆｜B ✅ 调度优化｜C ✅ 插件化｜D ✅ 工程稳定性｜E ✅ 评测测试｜F ✖
- 学生待办：0016 任务（pytest 两命令 + 故意改坏让测试抓住）、README 过目+录屏
- 剩：演示录屏 + 打包提交（提交硬要求 8.1：截图/录屏；8.4 邮件格式）
