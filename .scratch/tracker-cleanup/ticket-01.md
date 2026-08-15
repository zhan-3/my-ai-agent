# 01 — 票据清账：状态归真 + agent-eval spec 拆期

**Status:** resolved
**Blocked by:** None
**Type:** task
**Feature:** tracker-cleanup

## 背景

`.scratch/` 里大量已完成的票仍标 `ready-for-agent`，tracker 状态失真会让后续 agent
重复实现或误判优先级。另外 agent-eval spec 把 MVP 和二期愿景装在一起，永远无法关闭。
本票纯文档操作，**零代码改动**。

## What to build

### 1. 逐票核实并改状态

对下表每张票：先用表中「验证方法」确认代码确实落地，确认后把 `Status:` 改为
`resolved`，并在文件末尾追加 `## Answer` 段（2-4 行：落地在哪些文件/测试、
对应 commit（`git log --oneline --all -- <相关文件>` 找），若已有 Answer 段则只补缺）。
**验证不通过的票不许改状态**，在票尾 `## Comments` 记录核实结果。

| 票 | 验证方法 |
|---|---|
| `.scratch/e2e-matrix/ticket-05.md` | `grep -n "E2E-0[5-8]" tests/test_endtoend.py` 四个场景都在 |
| `.scratch/sse-error/ticket-06.md` | `grep -n "midstream\|final.*None\|def test.*stream" tests/test_webapp.py` 对照票内表格逐路径核对；有缺的路径记 Comments，缺项少可顺手判定是否 resolved（部分完成则状态改 `needs-info` 并列缺项） |
| `.scratch/subtask-split/ticket-07.md` | `grep -n "_split_subtasks" src/xiao_wen/intent.py tests/test_intent_split.py` |
| `.scratch/single-backend/ticket-08.md` | `grep -rn "InMemoryBackend" src/` 应无实现（仅注释提及）；conftest.py 用 POSTGRES_TEST_URL |
| `.scratch/disambiguation/spec.md` + `issues/01~04` | `src/xiao_wen/disambiguation.py` 存在、`tests/test_disambiguation.py` 存在、E2E-04/08 在 endtoend 里；四张 issue 逐一对 checklist |
| `.scratch/agent-eval/issues/01-trace-harness.md` | `src/xiao_wen/eval/trace.py`、`eval/metrics.py`、`scripts/eval/run.py` 存在且 checklist 项都能对上 |
| `.scratch/agent-eval/issues/01-intent-harness.md` | 同上（这是旧版 01 票，见下条） |

### 2. agent-eval 双 01 票归档

`issues/01-intent-harness.md` 与 `01-trace-harness.md` 编号冲突（前者是早期版本）。
处理：在 `01-intent-harness.md` 顶部 Status 行下加一行
`Superseded-by: 01-trace-harness.md（后者为现行版，本票保留作历史）`，状态改 `resolved`。

### 3. agent-eval spec 拆期

`.scratch/agent-eval/spec.md` 已落地部分：trace harness（#01）、judge 层（#02）、
样本铺开（matrix 243 + synthetic 48）。未落地：embedding 意图层（D2）、模拟器样本
正式通道、D5 七集中的五集（tools/rag/preference/sessions/adversarial）、user stories
#9/#12/#15（错误聚类/字数护栏/生产反馈闭环）。

操作：
- spec.md 顶部 Status 改为 `resolved`，并在 Status 行下加：
  `Note: phase-1（trace/judge/样本铺开）已交付；剩余范围移至 spec-phase2.md`
- 新建 `.scratch/agent-eval/spec-phase2.md`：Status: `needs-triage`（让人重新排优先级），
  内容 = 从原 spec **原文摘录**未落地的 D2、D5 剩余五集、stories 6/7/9/12/13/14/15
  相关段落，加一段开头说明来源。不新写设计，只搬运 + 标注「摘自 spec.md，
  phase-1 交付时未实现」。

### 4. 黄金集盲区登记（只开票不实现）

新建 `.scratch/agent-eval/issues/03-stats-intent-golden.md`，Status: `ready-for-agent`，
内容（简短即可）：黄金集「差旅统计」意图 0 样本（eval_runs/latest/report.md 混淆矩阵
该行全空），外部插件意图路由从未被回归验证。What to build：往
`tests/data/intent_golden.jsonl` 加 8-10 条差旅统计样本（「我今年出差几次了」「统计下
我常去哪些城市」等），跑 `--set intent` 维持 100%。

## 不做

- 任何 src/tests 代码改动
- git push（人来做）

## 验收

- [ ] 上表每票核实记录 + 状态归真
- [ ] spec 拆期完成，spec-phase2.md 存在且只含搬运内容
- [ ] 03-stats-intent-golden.md 已建
- [ ] `grep -rn "Status" .scratch/*/spec*.md .scratch/*/ticket-*.md .scratch/*/issues/*.md`
      输出贴进本票 `## Answer`（清账后全景快照）

## Answer

已清账。核实结果：tracker-cleanup 范围内的票**代码全部已落地**（Answer 段齐全，
测试文件确认存在），仅 Status 未翻——本票纯归真 + 拆期，零代码改动。

- 翻 resolved：e2e-matrix/05、sse-error/06（测试在 test_session.py:164/745/780 +
  test_webapp.py:355，四条路径全覆盖）、subtask-split/07、single-backend/08、
  disambiguation/spec + issues/01~04、agent-eval/issues/01-trace-harness
- 归档双 01 票：01-intent-harness 加 Superseded-by 01-trace-harness
- agent-eval/spec.md → resolved + Note；未落地范围移至 spec-phase2.md（needs-triage）
- 新增 agent-eval/issues/03-stats-intent-golden.md（差旅统计 0 样本盲区）

清账后 Status 全景快照：

```
.scratch/agent-eval/issues/01-intent-harness.md:17:**Status:** resolved
.scratch/agent-eval/issues/01-trace-harness.md:11:**Status:** resolved
.scratch/agent-eval/issues/01-trace-harness.md:41:Status: resolved
.scratch/agent-eval/issues/03-stats-intent-golden.md:3:**Status:** ready-for-agent
.scratch/agent-eval/spec-phase2.md:3:Status: needs-triage
.scratch/agent-eval/spec.md:3:Status: resolved
.scratch/disambiguation/issues/01-rules.md:7:**Status:** resolved
.scratch/disambiguation/issues/02-graph-hook.md:7:**Status:** resolved
.scratch/disambiguation/issues/03-golden-verify.md:7:**Status:** resolved
.scratch/disambiguation/issues/04-from-city-normalize.md:10:**Status:** resolved
.scratch/disambiguation/spec.md:3:Status: resolved
.scratch/e2e-matrix/ticket-05.md:19:**Status:** resolved
.scratch/intent-holdout/ticket-01.md:3:**Status:** ready-for-agent
.scratch/judge-hardening/issues/01-per-criterion-veto.md:3:**Status:** resolved
.scratch/judge-hardening/issues/02-mutation-canaries.md:3:**Status:** ready-for-agent
.scratch/judge-hardening/issues/03-vote-cost-and-fallback-guard.md:3:**Status:** ready-for-agent
.scratch/judge-hardening/spec.md:3:Status: ready-for-agent
.scratch/single-backend/ticket-08.md:20:**Status:** resolved
.scratch/split-guard/ticket-01.md:3:**Status:** resolved
.scratch/sse-error/ticket-06.md:16:**Status:** resolved
.scratch/subtask-split/ticket-07.md:13:**Status:** resolved
.scratch/tracker-cleanup/ticket-01.md:3:**Status:** claimed
```
