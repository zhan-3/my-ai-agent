# 02 — judge 金丝雀突变集（区分度证明）

**Status:** resolved
**Blocked by:** 01
**Type:** task

## 背景

judge 当前实测 20/20 全 PASS、均分 4.95（eval_runs/latest/judge_report.md）。它从未在
**已知坏回答**上验证过——无法排除「对任何回答都打高分」。本票构造一组手工突变样本
（金丝雀）：每条是刻意做坏的 trace 事件链，judge **必须**给低分/FAIL；另配好回答对照组
**必须** PASS。这是 judge 层自身的回归门禁，以后动 rubric/换 judge 模型都要先过它。

关键认知：**judge 的验收标准是「能把坏的打低」，不是「把好的打高」。**

## What to build

### 1. 数据 `tests/data/eval/judge_canaries.jsonl`

每行一条：

```json
{"id": "canary-01", "bad_type": "fabrication", "expect": "FAIL", "expect_max_score": 2,
 "events": [
   {"type": "input", "text": "一线城市的住宿标准是多少"},
   {"type": "classify", "intent": "知识问答", "reason": "问差旅政策"},
   {"type": "agent", "agent": "知识问答", "out": {"answer": "一线城市住宿标准为每晚 1800 元，五星级酒店可全额报销，无需审批。"}},
   {"type": "final", "answer": "一线城市住宿标准为每晚 1800 元，五星级酒店可全额报销，无需审批。"}
 ]}
```

对照组 `expect: "PASS"`，无 expect_max_score。

**必须覆盖的坏类型（每类 ≥2 条，共 ≥10 条坏 + ≥4 条好对照）：**

| bad_type | 构造方式 | 应触发的 rubric |
|---|---|---|
| fabrication | 编造具体政策数字/票价（如上例：编造 1800 元标准、"全额报销无需审批"） | 忠实度 → 一票否决 |
| forced_generation | 用户只说「帮我规划去广州出差」（无日期/天数/出发城市），final 却硬生成了完整三日行程含具体酒店和车次 | 合规性 → 一票否决 |
| off_task | 用户问「出差打车能报销吗」，final 答的是北京天气 | 任务完成 |
| verbosity | 正确答案外注水：同一信息换说法重复 4 遍 + 大段免责声明，总长 >500 字 | 简洁性 |
| leisure_not_rejected | 用户问「帮我规划三亚 5 日游度假」，final 热情给出了旅游攻略（正确行为应是归「其他」婉拒——本助手只服务企业差旅） | 合规性 → 一票否决 |

**好对照组（防止 judge 变成「见谁都 FAIL」）：**
- 1 条缺要素正确索取（抄 eval_runs/latest/judge_report.md 里的真实满分模式：列缺项 + 说明补全后可生成）
- 1 条政策问答正确回答（答案含「标准」等措辞、不编数字，如「一线城市住宿标准为每晚 500 元（差旅政策 v2）」——好坏对照的差别在于坏样本数字离谱且承诺无需审批）
- 1 条能力外请求正确说明边界 + 引导
- 1 条正常行程生成（要素齐全 → 给出逐日安排）

写样本时给每条加 `"note"` 字段一句话说明坏在哪，方便人工复核。

### 2. runner：`scripts/eval/run.py` 加 `--judge-canaries`

- 读 canaries jsonl → 每条直接 `judge.judge_with_votes(events, n=args.judge_n)`
  （**不跑 chat**——events 是手工构造的，零图调用，只烧 judge token）
- 判定：
  - `expect=FAIL` 的样本：verdict 必须 FAIL 且（有 expect_max_score 时）score ≤ expect_max_score
  - `expect=PASS` 的样本：verdict 必须 PASS
- 落盘 `eval_runs/latest/canary_report.md`：总通过率 + 明细表（id / bad_type / 期望 / 实际
  score+verdict+vetoed_by / 通过与否）+ 失败样本的 reasons 全文
- 任一样本不符 → exit 1（这就是 judge 层的门禁语义）

### 3. 测试 `tests/test_judge_canaries.py`

- 无 LLM 部分：canaries 数据文件可加载、schema 齐全（每条有 id/bad_type 或对照标记/
  expect/events，events 含 input+final）、坏类型五类都有覆盖、好对照 ≥4 条
- `@pytest.mark.integration` 部分（真 judge 模型）：实跑全部金丝雀，断言全部符合预期。
  失败时打印每条的 score/verdict/reasons，方便调 rubric。

## 不做

- 自动生成突变（LLM 产坏样本）——先手工 14 条，二期再自动化
- 把金丝雀挂 CI——等实跑稳定后另开票

## 验收

- [ ] `uv run pytest tests/test_judge_canaries.py -m "not integration" -q` 全绿
- [ ] 门禁四步全绿（`scripts/gate.sh`）
- [ ] 实跑：`uv run python scripts/eval/run.py --judge-canaries`（需 .env 密钥）
      **全部 14+ 条符合预期**。若有金丝雀被 judge 放过（坏样本 PASS）：
      不许改样本迁就 judge——这正是发现的 rubric 漏洞，把失败明细写进本票
      `## Comments` 区，状态改 `needs-human`，等人决定是否改 rubric 锚点
      （rubric 改动需重新做人机一致率校准，不在本票范围）。

## 实现提示

- events 的字段形状抄 `judge.build_judge_input`（src/xiao_wen/eval/judge.py）认的四种
  type：input/classify/agent/final；agent 事件的 out 里只需 answer。
- 政策数字什么算「编造」：看 `data/` 下知识库文档或 tests 里 RAG 测试的断言值，
  坏样本的数字要与真实政策明显冲突（如真实 500 → 坏样本 1800 + 无需审批）。
- `--judge-canaries` 与 `--with-judge` 互斥或独立子命令均可，跟随 run.py 现有 argparse 风格。

## Comments

金丝雀集实跑 **10/14 符合预期，4 条坏样本被 judge 放过** → 按票规转 `needs-human`。
金丝雀集、runner、测试本身已落地且工作正常（它正确识别出 judge 抓不住的样本），
失败的不是金丝雀，是 judge 的 rubric/聚合层。发现的 3 类漏洞：

### 漏洞 1：fabrication 检测无政策锚（canary-fab-01）
- 现象：编造「一线城市住宿标准 1800 元/晚、无需审批全额报销」（真实 500）→ judge 给 5 PASS，
  理由是「与提供的政策上下文完全一致，未编造任何数字」。
- 根因：`build_judge_input` 只喂 input/classify/agent/final，**没有喂政策 ground-truth**。
  judge 对「1800 元」这类听起来合理但违反政策的数字无法判定；而 fab-02（高铁 88 元）能被抓
  是因为 88 元违反 judge 自身常识。即 fabrication 检测目前依赖 judge 常识，不是政策锚定。
- 待决策：是否在 judge 输入里注入政策上下文（如 agent 实际检索到的 RAG 片段）或维护
  一张小额政策 ground-truth 表供 judge 比对。

### 漏洞 2：verbosity 非否决项，聚合层洗白（canary-verb-01 / verb-02）
- 现象：judge 明确写出「严重注水、明显违反简洁性要求」，却给 4 PASS。
- 根因：`VETO_CRITERIA` 只有忠实度/合规性；简洁性=2 时平均 (5+5+5+2+4)/5=4.2 → 4 → PASS。
  即 judge 看得到注水，聚合层把它洗白了。
- 待决策：是否把「简洁性」纳入否决项，或给注水单独设硬阈值（如简洁性 ≤2 直接 FAIL）。

### 漏洞 3：leisure 婉拒语义漂移（canary-leisure-02）
- 现象：「帮我规划春节回老家自驾游」→ 5 PASS，judge 认为「非差旅请求正确归为其他并给出
  合理路线，合规性满分」。
- 根因：rubric 合规性写「非差旅请求正确归「其他」**或婉拒**」，judge 把「归其他」（意图标签）
  当成了「给攻略也合规」，没有执行「婉拒」语义。且同类 leisure-01（三亚度假）被忠实度否决、
  leisure-02 漏过——leisure 识别本身不一致。
- 待决策：rubric 合规性锚点是否明确「休闲请求一律婉拒、不提供攻略」，并加一条休闲样本
  进黄金集校准。

> 注：以上 rubric 改动均需重新做人机一致率校准，超出本票范围，故转 needs-human。

### 进展更新（拍板 ①② 后）

- **漏洞 2（verbosity）已修**：`VETO_CRITERIA` 从 tuple 改为 `{"忠实度":2, "合规性":2, "简洁性":1}`
  ——简洁性 ≤1（机械重复式极端注水）才否决，普通啰嗦=2 不否决。实跑 verb-01/02 均
  简洁性=1 → 现转 FAIL（否决:简洁性）。
- **漏洞 3（leisure）已修**：rubric 合规性措辞改为「非差旅/休闲请求一律婉拒并引导回企业
  差旅，不得提供旅游攻略或行程」；与 `other_agent.run()` 真实行为对齐。新增 good-05
  （休闲婉拒正确对照）。实跑 leisure-02 转 FAIL（否决:合规性），good-05 PASS。
- **漏洞 1（fabrication）未修**：fab-01 仍 5 PASS。单独开票
  `04-fabrication-policy-anchor.md` 追踪（见下方决策）。

当前金丝雀 **14/15 符合预期**，唯一红灯 = fab-01（漏洞 1，见 04 票）。
门禁四步全绿（239 passed + 黄金集 84/84）。正常样本无回归（--with-judge 4/4 全 5 PASS）。

## Answer

金丝雀集交付完成：`tests/data/eval/judge_canaries.jsonl`（15 条：10 坏 + 5 好对照）、
`--judge-canaries` runner（落盘 canary_report.md，任一样本不符 exit 1）、
`tests/test_judge_canaries.py`（无 LLM schema/覆盖测试 + integration 实跑门禁）。

首跑 10/14 暴露 3 类 rubric 漏洞 → 本票 Comments 记录。拍板后：①② 在本票就地修复，
③（fabrication 政策锚）单独开票 `04-fabrication-policy-anchor.md` 追踪。

当前金丝雀 14/15，唯一红灯 fab-01 由 04 票持有；门禁四步全绿。
