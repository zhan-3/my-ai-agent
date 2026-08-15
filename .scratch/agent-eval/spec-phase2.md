# 晓问 Agent 评测体系 —— phase 2（未交付范围）

Status: needs-triage
Type: spec
Feature: agent-eval

> 本文从 `spec.md` 原文摘录 phase-1 交付时**未实现**的范围，供重新排优先级。
> phase-1（已交付）：trace harness（#01）、judge 层（#02）、样本铺开
> （matrix 243 组合 + synthetic 48 变体）、intent 黄金集 84 条。
> 出处：`.scratch/agent-eval/spec.md`（已标 resolved）。

---

## 未落地项

### D2. embedding 意图层（降级候选，不替换主链路）

- 形态：`classify()` 内部 `INTENT_CLASSIFY=llm|embedding` 开关（env 默认 llm）。
  embedding 模式 = 用户输入（必要时拼 recent 尾部）+ 每个意图的参考样本 → 向量 →
  余弦相似度取最高意图；低于阈值 → Unknown 出路（走「其他」+ 如实说明）。
- 参考样本来源：黄金集 84 条（每条意图 ~12 条）起步，模拟器样本增量补充。
- 验收：黄金集 84 条双模式跑分对比。embedding 模式意图准确率显著低于 LLM 模式
  （< 0.95 或低于 LLM 模式 3pt+）→ 不允许切换上线，只能留在候选。
- 实现约束：复用 `rag.EMB_MODEL` 接缝与 DashScope embedding（不新增第三方）；
  索引构建/复用策略照 RAG 现状（磁盘复用零消耗）。

### D5. 测试集（剩余六集）

七集中 intent 已落地；剩余：**itinerary、tools、rag、preference、sessions
（多轮 + 状态断言）、adversarial（非差旅/超长/模糊日期/prompt injection/订票订酒店边界）**。
每用例必带 `expected_*` + `source(human|sim|prod)`。

### 未落地 User Stories

- **#6** 用户模拟器自动产带标签对话样本（`scripts/ai_user_sim.py` 已存在，正式入集通道未做）
- **#7** 每个样本带 source（human/sim/prod）——runner 已支持该字段，数据文件尚未铺开
- **#9** 失败输入自动聚类（embedding 复用），发现系统性失败话术
- **#12** 输出字数双向护栏（防注水/防敷衍）+ 成本护栏（token/工具调用/耗时）
- **#13** 工具调用评测（该不该调/调对/参数/降级/浪费）走规则层
- **#14** 会话集断言记忆状态变化（偏好/历史是否真的写入）
- **#15** 生产反馈闭环（点踩/失败 → 新黄金用例 → 回归全量重跑）
- **#16**（部分）eval 失败 exit 1 挡 CI——run.py 已有退出码语义，CI 接线未做

## 关联（摘自 spec.md Out of Scope，保持不变）

- 反射 pass（critique 修订）产品化、生产反馈前端埋点（点赞/点踩 UI）、
  采样一致性 N=3-5 多模型投票、embedding 意图层**替换** LLM 主链路——均仍不在范围。

## 实施顺序参考（原 spec Further Notes 的依赖链，仍适用）

1. ai_user_sim 产样本入集（喂 judge 集 + 给 embedding 层攒参考样本）
2. embedding 意图层（D2）——依赖样本到位，双模式跑分验收
3. D5 剩余五集按「能规则/结构层判定就不上 judge」逐个落地
