# 晓问 Agent 评测体系设计

Status: needs-triage
Type: spec
Feature: agent-eval

> 目标：把「这轮改完好不好」从拍脑袋变成可量化、可回归、可定位的流程。
> 现状基础：单元 101 + 集成 15（`docs/test-map.md`）、意图黄金集 `scripts/golden_intents.py`、AI 用户模拟器 `scripts/ai_user_sim.py`。本 spec 在其上补**行为级/端到端评测**，不替代现有门禁。

---

## 1. 评测对象（五层，从下到上）

| 层 | 入口 | 已有覆盖 | 本体系补什么 |
|---|---|---|---|
| 意图分类 | `intent.classify()` | 黄金集脚本 | 并入统一 harness，出混淆矩阵 |
| 子 Agent 产出 | `agents/*` | 结构断言（test_itinerary 等） | 语义质量（judge） |
| 工具调用 | `web.py` @tool | 集成用例 | 工具选择/参数/降级指标 |
| 会话闭环 | `session.chat()` | test_session/test_endtoend | trace 全量采集 + E2E 状态断言 |
| 外部扩展 | `plugins/`（含未来 MCP） | test_plugin | 协议层评测（见 §3.5） |

评测三层跑法，成本递增：
1. **规则层**：无 LLM，秒级（契约校验/字数/意图相等/工具名相等）。
2. **结构层**：pydantic 结构匹配（subtask 列表、plan.days、要素集合）。
3. **judge 层**：LLM-as-judge，烧 token，`--with-judge` 开关，只进 CI master push。

---

## 2. trace：中间输出采集（评测的事实基础）

没有 trace 就没有错误分析——每个失败用例必须能回放「它到底哪一步错了」。

采集点（复用 `session.py stream_chat` 的 `astream_events` 机制，但评测走 `chat()` 同步路径 + 显式 recorder）：

```text
input / recent
  → classify: {intent, reason, subtasks[]}
  → dispatch: 路由到的 agent 名（p_* 分支展开）
  → 每 agent: 入参（注入的记忆/要素）、出参（plan dict / answer / tool 序列）
  → tool calls: [tool_name, args, result, error?]
  → final: {answer, plan(契约校验后), intent, reason}
  → memory 写回: [user_msg, assistant_msg, 偏好/历史变更]
```

- 落盘：`eval_runs/<case_id>/trace.jsonl`，与 `metrics.json`、`errors.jsonl` 同目录。
- trace 即评测的「中间输出」，也是后面错误分析的输入；结构上做成 pydantic 模型（`TraceRecord`），保证录制稳定。

## 3. judge：三层评判标准

**规则层（确定性，无 LLM）**
- 契约：`contract.plan_or_none` 通过率（结构不符→降级也算分，但要单列「降级率」）。
- 要素：行程 agent 输出是否覆盖输入中已给出的差旅要素；缺失时是否先索取而非硬生成（CONTEXT 语义）。
- 字数：见 §3.1 限制项。
- 意图/工具名/参数：精确相等。

**结构层**
- subtasks 精确匹配（黄金集已有此逻辑，抽成公共校验器）。
- plan.days 数量 == 请求天数、日期可解析、每日字段齐全。

**judge 层（LLM-as-judge，rubric 驱动）**
- rubric 直接抄 CONTEXT.md 领域规则，逐条打分：
  1. **任务完成**：是否真的办成了用户要的事（规划出可用行程/答出政策/记下偏好）。
  2. **忠实度（groundedness）**：政策问答是否只讲知识库内容，不编造标准。
  3. **合规性**：仅服务企业差旅；非差旅一律拒绝（归「其他」）；要素不全先索取。
  4. **简洁性**：不注水（配合字数指标）。
  5. **得体性**：拒绝/追问语气是否自然。
- 输出 `{score: 1-5, reasons: [], verdict: pass/fail}`，temperature=0，json_mode。
- judge 模型独立配置（`EVAL_JUDGE_*` env），与被评模型分开，避免自评偏差；同一用例 N 次跑取多数票。
- judge 自身质量校验：抽 10% 用例人工复核 judge 评分，记录人机一致率（judge 漂移监控）。

### 3.1 输出字数限制（双向）

- **上限**：防注水/防 token 浪费。规则层统计 answer 字数 + plan 体积；超过上限（如 answer > 800 字）直接记 over-length，judge 简洁性给低分。
- **下限**：防敷衍。拒绝类（「其他」意图）回答 < 10 字、缺项提示只列一半要素 → under-length。
- **成本护栏**：评测报告单列每用例 token 数/工具调用次数/耗时，防止「分数靠堆 token」。
- 评测 harness 自身也给 judge 调用的 `max_tokens` 设上限（judge 输入即 trace，trace 可能很大，需截断策略：保留 classify + 目标 agent + tool 段）。

## 4. tools 调用评测

针对 `web.py`（天气/汇率/空气质量）与未来任意工具：

| 指标 | 定义 | 判据来源 |
|---|---|---|
| 该不该调 | 查询含实时信息 → 应调；纯政策/记忆类 → 不应调 | 工具黄金集 label |
| 调对工具 | 天气问句 → `get_weather`，汇率 → `get_exchange_rate` | 工具名相等 |
| 参数正确 | 城市/日期解析正确（未来 7 天预报日期解析已有测试） | 参数校验器 |
| 降级正确 | API 失败 → 兜底文案而非裸崩/编数据 | `stability` 规则断言 |
| 调用浪费 | 同轮重复调同参数工具 | 规则统计 |

- 数据：`tests/data/eval/tools.jsonl`，每条 `{input, expected_tool?, expected_args?, should_call}`。
- 指标：工具精确率（调对的/调的总数）、召回率（调对的/该调的）、参数正确率、降级正确率。

## 5. MCP 评估（前瞻性协议层）

现状：晓问工具是 langchain `@tool` 直连，未接 MCP。评测体系把 MCP 当作**外部工具接入协议**来评估，为将来接入预留，分四层：

1. **元数据层**：MCP server 的 tool 清单/描述/输入 schema 与注册表 manifest 语义一致（discover 正确性）。
2. **契约层**：JSON-RPC 调用往返——参数校验、错误码、超时、流式输出，mock server 上跑负例（断连/超时/非法参数）。
3. **等价性**：同一组工具黄金用例分别驱动「@tool 实现」与「MCP 包装实现」，对比工具名/参数/结果一致性——保证协议封装不改变行为。
4. **效果层**：接 MCP 工具后任务完成率（judge）是否不降、成本（延迟/token）是否可控。

落地形态：`eval/mcp/` 一套 pytest（契约层可离线 mock，等价性/效果层标 integration），与 `test_plugin` 同一哲学：外部件可插拔、可评测、可回归。

## 6. reflection：自反思与增益度量

两件事分开：

**A. 产品内反思（可选能力）**：行程 agent 生成后加一次 critique pass——按 checklist 自查（要素覆盖/日期一致/偏好遵守/边界合规），不满意则修订。评测要回答「加了值不值」：
- **反射增益** = 修订后 judge 分 − 修订前 judge 分（同用例）。
- **回退率**：修订把对的改错的占比（>10% 说明反思 prompt 有毒，别上）。

**B. 评测自身的自一致性**：同用例跑 N 次（N=3~5），记录答案/意图方差 → 稳定性指标。既测模型非确定性，也测反思是否增加不稳定。

## 7. 外部反馈闭环（评测集的生命周期）

评测集不能只靠人工写——生产与评测互相喂养：

```text
生产（前端 点赞/点踩 + 失败日志）
  → 采集器：低分/点踩 → trace 快照 + 用户原话
  → triage：按 triage-labels 分流（needs-triage → 人工/agent 确认）
  → 沉淀：确认的坏例转成新黄金用例（golden set 增量），或转 ADR（明确能力边界）
  → 回归：eval 全量重跑，坏例必须变好，好例不得变坏
```

- 显式反馈：前端交互留 `feedback` 埋点（点赞/点踩/评语），落库供采集。
- 隐式反馈：生产 trace 与黄金集的 diff（如意图命中率低于阈值的新输入聚类）。
- 这条闭环是「系统性的错误分析」的持续来源，不是一次性动作。

## 8. 测试集设计（针对设计测试集）

按能力域分集，统一 JSONL schema：`{id, input, recent?, expected_*(结构化), rubric?, note, source(human|sim|prod)}`

| 集 | 文件 | 断言方式 | 现成素材 |
|---|---|---|---|
| 意图集 | `tests/data/eval/intent.jsonl` | 规则层（intent+subtasks 精确） | 复用 `intent_golden.jsonl` + 扩展对抗 |
| 行程集 | `itinerary.jsonl` | 结构层（要素/天数/日期）+ judge 合理性 | test_itinerary 用例、E2E 素材 |
| 工具集 | `tools.jsonl` | 规则层（该不该调/调对/参数） | test_web 用例 |
| RAG 集 | `rag.jsonl` | judge 忠实度 + 命中文档断言 | test_rag 素材 |
| 偏好集 | `preference.jsonl` | 规则层（category/content + 追加 vs 覆盖） | test_memory 用例 |
| 会话集（E2E） | `sessions.jsonl` | 多轮脚本 + 状态断言 + judge | ai_user_sim 素材（人设/目标/表达分支） |
| 对抗集 | `adversarial.jsonl` | 规则层 + judge | 非差旅、超长输入、模糊日期、prompt injection、边界动作（订票/订酒店） |

- 每个用例必须带 `expected_*`，能走规则/结构层的就不依赖 judge——judge 只负责「规则层测不了的语义质量」。
- 用例来源三通道：人工编写（领域规则驱动）、sim 采集（素材真实度）、生产反馈（见 §7）。来源字段保证可追溯。

## 9. E2E 评估指标（指标总表）

| 指标 | 计算 | 层 |
|---|---|---|
| 意图准确率 | intent 相等 + subtasks 精确匹配（整体 + 按意图分） | 规则 |
| 任务完成率 | 契约/结构校验通过 且 judge ≥ 阈值 | 规则+judge |
| 行程结构完整率 | plan 非 None 且 days 数/日期/字段合规 | 规则 |
| 降级率 | plan 结构不符→None 的占比（要低，但可容忍） | 规则 |
| 工具精确率 / 召回率 | 见 §4 | 规则 |
| 拒绝正确率 | 非差旅 → 归「其他」且回应得体 | 规则+judge |
| 偏好写正确率 | 追加/覆盖语义正确 | 规则 |
| RAG 忠实度 | judge groundedness 均分 | judge |
| 字数合规率 | over/under-length 用例占比 | 规则 |
| 效率 | 平均 token / 工具调用次数 / 耗时 | 规则 |
| 自一致率 | N 次运行意图/答案一致比例 | 规则 |
| 反射增益 / 回退率 | 见 §6 | judge |
| judge 人机一致率 | 抽样人工复核 | 运维 |

E2E 会话集额外断言**状态变化**：跑完一轮后记忆里是否多了一条偏好/历史（读 `store` 验证），而不只看回复文本。

## 10. 系统性错误分析

每次 eval 跑完自动产出 `errors.jsonl` + `report.md`：

1. **按层归类**：意图错 / 路由错 / 要素提取错 / 生成错 / 工具错 / 记忆写错 / 格式错——每类附 trace 快照。
2. **混淆矩阵**：意图集逐意图 实际×期望（复用 golden 脚本的 by_intent 统计升级版）。
3. **错误聚类**：失败输入做 embedding（复用 DashScope 向量）聚类，找出「哪一类用户话术系统性失败」——喂给 prompt 修改或 golden 扩充。
4. **根因判定**（每类给一个候选 + 证据）：
   - 提示词缺陷（trace 里 reason 文本错/要素丢）→ 修 prompt
   - 边界规则缺失（漏了某业务动作）→ 加规则/加 golden
   - 数据不足（RAG 没命中）→ 补知识库
   - 模型能力/非确定性（同输入多跑结果漂移）→ 记 ADR 或降级处理
5. **回归门禁**：阈值化——意图 ≥ 0.95（沿用 golden）、完成率 ≥ 0.9、工具精确率 ≥ 0.95 等；低于阈值 exit 1。分层：规则层全量跑（快、每次提交），judge 层 master push（烧 token）。

## 11. 落地结构（harness）

```text
scripts/eval/                      # 与 golden_intents.py 同层的可执行评测
  run.py            # --sets intent,tools,... --with-judge --threshold ...
  judge.py          # rubric 加载 + LLM-as-judge + 多数票
  trace.py          # TraceRecord 采集（包装 session.chat）
  report.py         # metrics / errors.jsonl / report.md / 混淆矩阵 / 聚类
src/xiao_wen/eval/  # 可被 pytest 引用的校验器（规则层/结构层纯函数）
tests/data/eval/    # 7 个 JSONL 集
```

依赖：不新增第三方——judge 走 `llm.get_llm()` 同款接缝（独立 env 配置），embedding 复用 DashScope。

## 12. 待决策点（open questions）

1. judge 用同模型（DeepSeek）还是换模型？成本 vs 独立性。
2. 字数上限具体值（800 字 answer / plan 体积）——先拿现有集成用例实测分布再定。
3. MCP 是否排期接入，还是只保留协议评测层（§5 四层中 1/2 层可先做，3/4 依赖真实接入）。
4. 反射 pass 是否要做成产品能力——取决于 §6A 的增益/回退率实测。
5. 生产反馈埋点（前端点踩）是否本期做，还是先用手动收集。
