# 晓问 Agent 评测体系（layer 2/3）+ 意图分类 embedding 降级层

Status: ready-for-agent
Type: spec
Feature: agent-eval

> 一句话：把「这轮改完好不好」从拍脑袋变成可量化、可回归、可定位的流程；同时把
> 意图分类从「只靠 LLM」升级为「LLM 主 + embedding 降级候选」，开关可切、黄金集验收。
> 现状：eval-01（规则层）已毕业（黄金集 84 条 100%）；`golden_intents.py`、`ai_user_sim.py`
> 已存在；本 spec 补 **judge 层（layer 3）+ 用户模拟器产样本（layer 2 的样本通道）+ embedding 意图层**。

---

## Problem Statement

1. **评测靠拍脑袋**：改完一轮（改 prompt / 加规则 / 换模型）「好不好」没有量化口径。
   单元测试只保证不崩，不保证答得对——意图错、要素丢、编造政策这些「答错了但没崩」
   的问题现有门禁全测不出来。用户实测 bug（「临沂」6 次提取不稳、「规划」词缺失）都是
   这种「没崩但错了」的典型，等用户来报才知道。
2. **意图分类只靠 LLM 不稳**：实测同输入连续 6 次提取 from=待定；分类也出现过同输入
   两次不同结果。LLM 有成本、有方差、离线/无 key 时不可用。
3. **embedding 消耗被关注**：知识问答每次检索吃 query embedding；用户已提出想省。
   若意图层引入 embedding 匹配，必须可关、可量化收益，不能无脑加码。

## Solution

- 评测体系三层跑法落地（规则层已毕业 → 补结构层统一 harness + judge 层），
  每次改动有量化分数、失败可回放到具体一步（trace）。
- 意图分类：`intent.classify()` 内部加 embedding 匹配路径（开关 `INTENT_CLASSIFY`），
  默认 LLM 主链路不变；embedding 作为降级候选，**黄金集 84 条双模式跑分**，掉分不许上线。
- 样本通道：`ai_user_sim.py`（已存在）产出带标签对话 → 沉淀进意图集/行程集/会话集，
  喂给 judge 评测与 embedding 层参考样本。

## User Stories

1. 作为开发者，我想对任何一次「这轮改完」跑一条命令拿分数，以便不靠感觉判断好坏。
2. 作为开发者，我想让每个失败用例带 trace 回放（意图→路由→agent→工具→记忆写回），
   以便 5 分钟内定位「它到底哪一步错了」，而不是整轮重看。
3. 作为开发者，我想让评测分三层跑（规则/结构/judge），以便日常提交只跑秒级规则层，
   烧 token 的 judge 只在 master push 跑。
4. 作为开发者，我想让意图分类可切 LLM/embedding 双模式，以便成本敏感期或离线环境
   降级不瘫痪。
5. 作为开发者，我想让 embedding 模式跑黄金集 84 条拿对比分，以便用数据决定它能否上线。
6. 作为开发者，我想让用户模拟器自动产带标签对话样本，以便评测集不靠手写耗尽。
7. 作为开发者，我想让每个样本带 source（human/sim/prod），以便追溯评测集来源。
8. 作为开发者，我想看意图混淆矩阵（逐意图 实际×期望），以便知道哪个意图边界在漏。
9. 作为开发者，我想让错误失败输入自动聚类（embedding 复用），以便发现「哪一类话术
   系统性失败」。
10. 作为开发者，我想让 judge 按 CONTEXT 领域规则打 5 分 rubric（完成/忠实/合规/简洁/得体），
    以便语义质量可量化。
11. 作为开发者，我想让 judge 与被评模型独立配置、temperature=0、多数票，
    以便避免自评偏差与方差。
12. 作为开发者，我想让输出有字数双向护栏（防注水/防敷衍）+ 成本护栏（token/工具调用/耗时），
    以便分数不是靠堆 token 堆出来的。
13. 作为开发者，我想让工具调用评测（该不该调/调对/参数/降级/浪费）走规则层，
    以便实时信息类能力可回归。
14. 作为开发者，我想让会话集跑完断言记忆状态变化（偏好/历史是否真的写入），
    以便不只信回复文本。
15. 作为开发者，我想让生产反馈闭环（点踩/失败 → 沉淀成新黄金用例 → 回归全量重跑），
    以便评测集越用越准、坏例必须变好、好例不得变坏。
16. 作为开发者，我想让 eval 失败低于阈值时 exit 1 挡 CI，以便门禁自动拦回归。

## Implementation Decisions

### D1. 评测缝（最高 seam，先确认过的三个）
- **分类缝**：`intent.classify(recent, user_input) -> IntentResult` 签名不变；
  embedding 路径做 `classify()` 内部候选（见 D2）。不新开接口。
- **评测缝**：`scripts/eval/` 扩展（run.py 已有，新增 judge.py / trace.py / report.py）；
  纯函数校验器（规则/结构层）进 `src/xiao_wen/eval/` 供 pytest 引用——唯一新增 seam。
- **样本缝**：`scripts/ai_user_sim.py` 输出带 `source=sim` 标签入 `tests/data/eval/*.jsonl`，
  不新开缝。

### D2. embedding 意图层（降级候选，不替换主链路）
- 形态：`classify()` 内部 `INTENT_CLASSIFY=llm|embedding` 开关（env 默认 llm）。
  embedding 模式 = 用户输入（必要时拼 recent 尾部）+ 每个意图的参考样本 → 向量 →
  余弦相似度取最高意图；低于阈值 → Unknown 出路（走「其他」+ 如实说明）。
- 参考样本来源：黄金集 84 条（每条意图 ~12 条）起步，模拟器样本增量补充。
- 验收：黄金集 84 条双模式跑分对比。embedding 模式意图准确率显著低于 LLM 模式
  （< 0.95 或低于 LLM 模式 3pt+）→ 不允许切换上线，只能留在候选。
- 实现约束：复用 `rag.EMB_MODEL` 接缝与 DashScope embedding（不新增第三方）；
  索引构建/复用策略照 RAG 现状（磁盘复用零消耗）。

### D3. trace（评测的事实基础）
- `TraceRecord`（pydantic）：input/recent → classify{intent,reason,subtasks} →
  dispatch(agent 名, p_* 展开) → 每 agent 入参/出参 → tool calls → final →
  memory 写回。落盘 `eval_runs/<case_id>/trace.jsonl` + `metrics.json` + `errors.jsonl`。
- 评测走 `session.chat()` 同步路径 + 显式 recorder（不依赖 astream_events）。

### D4. judge（layer 3，LLM-as-judge）
- rubric 抄 CONTEXT.md 领域规则五条：任务完成 / 忠实度(groundedness) / 合规性 /
  简洁性 / 得体性。输出 `{score:1-5, reasons, verdict}`，temperature=0，json_mode。
- judge 模型独立 env（`EVAL_JUDGE_*`），与被评模型分开；同用例 N 次取多数票；
  `--with-judge` 开关，只进 CI master push。
- judge 自身质量：抽 10% 人工复核，记录人机一致率（漂移监控）。

### D5. 测试集（统一 JSONL schema，能规则/结构层就不上 judge）
- 七集：intent（复用 intent_golden.jsonl 84 条 + 对抗扩展）、itinerary、tools、rag、
  preference、sessions（多轮 + 状态断言）、adversarial（非差旅/超长/模糊日期/
  prompt injection/订票订酒店边界）。
- 每用例必带 `expected_*` + `source(human|sim|prod)`；意图集已含消歧用例（5 条）。

### D6. 指标与门禁（阈值化）
- 指标总表沿用原 spec：意图准确率（≥0.95）、任务完成率（≥0.9）、工具精确率（≥0.95）、
  拒绝正确率、偏好写正确率、RAG 忠实度、字数合规率、效率（token/调用/耗时）、自一致率。
- 分层：规则层全量每次提交跑；judge 层 master push；低于阈值 exit 1。

### D7. 错误分析
- `errors.jsonl` + `report.md`：按层归类（意图/路由/要素/生成/工具/记忆/格式）、
  混淆矩阵、失败输入 embedding 聚类、每类给根因判定（prompt 缺陷/边界规则缺失/
  数据不足/模型非确定性 → 修 prompt / 加规则 / 补知识库 / 记 ADR）。

## Testing Decisions

- **好测试的标准**：只测外部行为（意图结果、结构契约、记忆状态、judge 分数），
  不测内部实现细节；能规则/结构层判定的用例不上 judge（省 token、确定性）。
- **被测模块**：`intent.classify()`（双模式）、`src/xiao_wen/eval/` 校验器（纯函数）、
  `scripts/eval/*.py`（harness 自测）、`session.chat()`（trace 采集 + 状态断言）。
- **先例**：`test_disambiguation.py`（规则纯函数测试模式）、`test_webapp.py` 契约校验、
  `test_memory_backend.py` 记忆状态断言、`golden_intents.py` 的 by_intent 统计逻辑
  （升级为混淆矩阵时复用）、`test_plugin.py`（外部件可插拔可评测哲学）。
- **集成标记**：judge / 模拟器产样本 / 双模式跑分标 integration（烧 token 不进
  常规 unit 门禁），规则/结构层纯函数进常规 pytest。
- **黄金集基线**：84 条 100% 是回归底线，任何改动（含 embedding 层）不许掉。

## Out of Scope

- MCP 真实接入（仅保留协议评测层设计，§5 原 spec 中 1/2 层可后做）。
- 反射 pass（critique 修订）产品化——取决于增益/回退率实测，本期不排。
- 生产反馈前端埋点（点赞/点踩 UI）——本期先手动收集坏例。
- 采样一致性 N=3-5 多模型投票（disambiguation 二期，与意图层无关的已否决项）。
- 要素层消歧、航班/车次实时数据能力。
- embedding 意图层**替换** LLM 主链路（只做候选/降级，验收不过不上线）。

## Further Notes

- **实施顺序（依赖链）**：
  1. `src/xiao_wen/eval/` 纯函数校验器 + trace 采集（规则/结构层统一 harness，
     意图集 = 现有 84 条直接受益）。
  2. judge.py + `--with-judge`（layer 3 打通，rubric 从 CONTEXT 抄）。
  3. ai_user_sim 产样本入集（喂 judge 集 + 给 embedding 层攒参考样本）。
  4. embedding 意图层（D2）——依赖第 3 步样本到位，双模式跑分验收。
- **待定参数**：judge 模型选择（DeepSeek 同款 vs 独立）、字数上限具体值
  （先拿现有集成用例实测分布）、`--with-judge` 的 CI 触发条件（master push 是否够）。
- **关联**：ADR-0001（LLM 接缝——judge 走同款接缝、独立 env）、ADR-0004（RAG——
  embedding 复用 EMB_MODEL 与索引复用策略）、`docs/agents/issue-tracker.md`（发布载体）、
  CONTEXT.md（rubric 领域规则唯一来源）。
