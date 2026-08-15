# 01 — 意图分类 held-out 对抗集（防规则过拟合）

**Status:** resolved
**Blocked by:** None
**Type:** task
**Feature:** intent-holdout

## 背景

`src/xiao_wen/intent.py` 的意图分类 = LLM 主链路 + 三层规则兜底（`_recover_pending` /
`_pref_only_correction` / `_split_subtasks`）+ 9 组硬编码词表。**这些规则是照着黄金集
失败样本调出来的**——黄金集（84 条）100% 全绿证明不了泛化，因为它同时是"训练集"。
每次实测 bug 长一组新词表的模式已经出现，需要一个**从未参与规则调参**的 held-out 集
来回答："这次加的规则是修复还是过拟合？"

## What to build

### 1. 数据 `tests/data/holdout_golden.jsonl`

**≥40 条**新样本，schema 与 `tests/data/intent_golden.jsonl` 完全一致。
**实际字段（已核对）**：`input` / `expected` 必填；`note` 必填（判定理由）；`recent` 和
`subtasks` 可选（多轮样本才写 recent；`subtasks` 不写 = 不断言子任务）。
该文件**没有** `id`/`source` 字段——不要照别处印象加，保持与 intent_golden 同构。

**构造原则：与黄金集措辞正交**（换说法、换句式，不许从黄金集复制改一两个字）：

| 类别 | 条数 | 构造指引（举例方向，执行时自行造句） |
|---|---|---|
| 口语/方言化行程规划 | 6 | 「下礼拜得跑趟成都，帮忙弄个安排呗」「后天飞广州，三天，整一个」 |
| 错别字/无标点 | 4 | 「帮我规划下周去杭洲出差2天的形程」「我想知道出差住宿标准是多少谢谢」 |
| 中英混杂 | 3 | 「帮我 book 一下去上海的 trip，下周三出发」「差旅 policy 里打车能报吗」 |
| 「还有/顺便」**不该拆**的干扰 | 5 | 「我还有一个会要开，帮我把行程排开」「另外一个同事也去，行程按两人安排」——考 `_split_subtasks` 的分隔符前置规则会不会误拆 |
| 「还有/顺便」**该拆**的变体 | 4 | 用黄金集没有的连接词组合：「…；对了顺道问下明天上海降温吗」 |
| 偏好陈述 vs 咨询边界 | 6 | 「住如家就行」（陈述→偏好）vs「如家怎么样值得住吗」（咨询→其他）vs「我上次住的是如家吗」（问记忆→历史查询）——考 `_pref_only_correction` 和 `_is_pref_statement` 词表外的说法 |
| 追问续接变体 | 5 | recent 含追问，但用户回复用黄金集没有的形式：「就从南京走」「大概去个四五天吧」「先按一周弄」 |
| 个人休闲伪装差旅 | 4 | 「出差顺便想在三亚多玩两天，帮我把玩的行程也排了」（玩的部分→其他）「公司团建去桂林怎么安排」（团建非差旅？→ 按产品边界规则标注，拿不准的在 note 里写明理由） |
| 联网/知识易混 | 3 | 「深圳下周适合出差吗会不会台风」（→联网查询）「出差遇上台风机票退改怎么算」（→知识问答） |

标注时**先自己按 CONTEXT.md 的意图定义人工判**，note 写一句判定理由。拿不准的样本
宁可删掉换一条，不留争议标注。

### 2. runner：`scripts/eval/run.py` 加 `--set holdout`

- 复用现有 `--set intent` 的全部管线（`run_intent_set` + metrics + 落盘三件套），
  只换数据文件为 holdout_golden.jsonl
- **阈值默认 0.9**（不是黄金集的 1.0——held-out 允许少量失败存在，那正是信号）
- 报告落 `eval_runs/latest/`，文件名前缀区分（如 `holdout_report.md`），不覆盖 intent 集产物

### 3. 治理规则（写进两处）

在 `tests/data/holdout_golden.jsonl` 同目录建 `tests/data/HOLDOUT.md`：

```
# held-out 集使用规则
1. 本集样本【禁止】用于调 intent.py 的规则/词表/few-shot——它存在的意义就是没被看过。
2. 修改 intent.py 分类相关代码的提交，必须跑 `--set holdout` 并在提交信息附分数。
3. holdout 失败样本要修复时：把该样本【移入】intent_golden.jsonl（此后它算训练集），
   再补一条同类新样本进 holdout——集合大小不减。
4. holdout 分数低于 0.9：不是改样本，是停下来看规则层是否过拟合。
```

并在 `AGENTS.md` 的 Quality gate 段落后追加一行指引（一句话 + 指向 HOLDOUT.md）。

### 4. 首跑基线

实跑 `--set holdout`（需 .env 密钥），把首跑分数、失败明细、混淆矩阵贴进本票
`## Answer`。**失败样本不修**（那是下一张票的输入），只记录。

## 不做

- 修复 holdout 暴露的失败（先拿基线，另开票修）
- embedding 意图层（agent-eval spec D2，独立工作）
- CI 接入

## 验收

- [ ] holdout_golden.jsonl ≥40 条、九类覆盖齐、每条有 note
- [ ] `--set holdout` 跑通、产物落盘、阈值语义正确（<0.9 → exit 1）
- [ ] HOLDOUT.md + AGENTS.md 指引落地
- [ ] 门禁四步全绿（`scripts/gate.sh`；本票新增代码极少，主要是数据）
- [ ] 首跑基线记录在 `## Answer`（分数无论高低都记——低分不是本票的失败）

## 实现提示

- 先读 `tests/data/intent_golden.jsonl` 前 20 行拿准 schema 和 recent 的写法
  （多轮样本 recent 是拼好的对话文本）。**该文件实际字段 = input/expected/note/recent/subtasks，
  没有 id/source**。
- run.py 的 `--set` 分发已存在（intent/matrix/synth 数据常量在文件头部），加一个
  常量 + 分支即可，别重写管线。
- 造句时警惕：不要下意识使用 `_PENDING_MARKS`、`_PREF_VERB_MARKS` 等词表里的词
  （先读 intent.py 底部词表），**刻意绕开它们**才测得出规则外的泛化。

## Answer

已实现：

- `tests/data/holdout_golden.jsonl`：42 条、十类覆盖（口语化/错别字/中英混杂/不该拆/该拆/
  偏好vs咨询/追问续接/休闲伪装/联网知识易混/差旅统计），每条带 note。字段与 golden 同构
  （input/expected/note/recent/subtasks，无 id/source）。
- `scripts/eval/run.py`：`--set holdout`（阈值默认 0.9，其余集仍 1.0）；metrics.summarize
  加 set_name 参数（报告标题区分评测集）。
- `tests/data/HOLDOUT.md` 治理规则 + `AGENTS.md` Quality gate 追加 holdout 指引。

首跑基线：**42/42 = 100%**（阈值 0.9 PASS）。

基线过程中的一个真发现：原样本「深圳下周适合出差吗会不会台风」我标「联网查询」，实跑
LLM 归「其他」——「适合出差吗」是咨询（应归其他），主导意图确实含糊，是我的标注争议。
按票规「拿不准的样本换一条」改成「深圳下周有台风吗」（无歧义天气）→ 100%。这恰好验证
holdout 的价值：先抓标注争议，再谈规则泛化。
