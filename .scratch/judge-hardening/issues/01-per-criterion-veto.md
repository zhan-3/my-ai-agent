# 01 — judge 分维度分数 + 一票否决聚合

**Status:** resolved
**Blocked by:** None
**Type:** task

## 背景（不了解项目也能做）

`src/xiao_wen/eval/judge.py` 是 LLM-as-judge：五条 rubric（任务完成/忠实度/合规性/
简洁性/得体性）打分。当前 LLM 直接输出总分 `score`（五条平均取整）+ `verdict`。
问题：忠实度 1 分可被其他四条 5 分平均成 4 → PASS，与 rubric 的「编造明显事实 ≤2 分」
矛盾。本票改为：**LLM 输出分维度分数，总分与 verdict 由代码计算，忠实度/合规性 ≤2
一票否决**。

## What to build

### 1. `src/xiao_wen/eval/judge.py`

**JudgeOutput（pydantic，LLM 输出契约）改为：**

```python
class JudgeOutput(BaseModel):
    criteria: dict[str, int]   # 键 = 五条 rubric 中文名，值 = 1-5
    reasons: list[str]         # 逐条理由，5 条，与 rubric 顺序对应
```

（删掉 LLM 输出的 score/verdict——不再信 LLM 自己算总分。）

**JudgeVerdict（dataclass，对外结果）改为：**

```python
@dataclass
class JudgeVerdict:
    score: int                                    # 1-5，代码计算
    criteria: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    verdict: str = "FAIL"
    vetoed_by: str | None = None                  # 触发一票否决的维度名，未触发为 None
```

**新增纯函数（模块级，可单测）：**

```python
VETO_CRITERIA = ("忠实度", "合规性")

def aggregate(criteria: dict[str, int], reasons: list[str]) -> JudgeVerdict:
    """聚合规则（代码算，不信 LLM）：
    - score = round(五条平均)，用 int(x + 0.5) 语义（banker's rounding 不行，写死半进位）
    - 任一 VETO_CRITERIA 维度 ≤2 → verdict=FAIL 且 score=min(score, 2)，vetoed_by=该维度名
      （两个都 ≤2 时取第一个命中的）
    - 无否决时 verdict = PASS if score >= 4 else FAIL
    - criteria 缺少五条中任何一条 → score=0, verdict=FAIL, reasons 追加缺失说明（防 LLM 少给键）
    """
```

**`judge_once` 改动：**
- prompt 系统消息 `_JUDGE_SYSTEM` 的输出格式段改为：
  `输出严格 JSON：{{"criteria": {{"任务完成": 1-5, "忠实度": 1-5, "合规性": 1-5, "简洁性": 1-5, "得体性": 1-5}}, "reasons": [5条理由字符串]}}`
  并删掉「总分规则」句里让模型自己算总分/verdict 的部分（1-5 档语义描述保留，帮助定档）。
- LLM 返回后调 `aggregate(out.criteria, out.reasons)` 得 JudgeVerdict。
- 解析失败路径不变：`JudgeVerdict(score=0, reasons=["judge 解析失败/模型异常"], verdict="FAIL")`。

**`majority_vote` 改动：** 逻辑不变（score 众数、平局取高、取胜者那次的全部字段），
只需确保携带新字段 criteria/vetoed_by。

### 2. `scripts/eval/run.py` 的 `_run_judge`

- `judge_report.md` 增加分维度均分表：

```
## 分维度均分
| 维度 | 均分 | ≤2 次数 |
|---|---|---|
```

  （遍历 verdicts 的 criteria 统计；score=0 的解析失败样本跳过统计。）
- 明细表增加「否决」列：`vetoed_by or "-"`。
- `judge_samples.jsonl` 落盘时带上 criteria 和 vetoed_by 字段。

### 3. 测试 `tests/test_judge.py`

改现有 + 新增（全部无 LLM，纯函数/monkeypatch）：
- `test_aggregate_average_rounding`：criteria 全 4 → score 4 PASS；{5,5,4,4,4} → 平均 4.4 → 4 PASS
- `test_aggregate_veto_faithfulness`：忠实度=1 其余全 5 → verdict FAIL、score ≤2、vetoed_by="忠实度"
- `test_aggregate_veto_compliance`：合规性=2 其余全 5 → FAIL、vetoed_by="合规性"
- `test_aggregate_no_veto_on_conciseness`：简洁性=1 其余全 5 → 平均 4.2 → score 4 PASS（简洁性不否决）
- `test_aggregate_missing_criterion_fails`：只给 4 条 → score 0 FAIL
- `test_judge_once_parses_criteria`（改现有 `test_judge_once_parses_verdict`）：monkeypatch
  `get_judge_llm` 返回假模型（现有测试有先例，抄它的注入方式），断言 criteria 透传 + verdict 由代码算出
- `test_majority_vote_*` 两个现有测试适配新字段（构造 JudgeVerdict 时补 criteria）

## 不做

- 金丝雀突变集（票 #02）
- N=1 默认与回退阻断（票 #03）
- rubric 文案本身不动（锚点已经人机一致率校准过，改文案要重新校准）

## 验收

- [ ] `uv run pytest tests/test_judge.py -q` 全绿
- [ ] 门禁四步全绿：`scripts/gate.sh`（需先 `docker-compose up -d postgres` +
      `export POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test`）
- [ ] （有 .env 密钥时可选）`uv run python scripts/eval/run.py --set intent --with-judge
      --judge-sample 3` 实跑确认 judge_report.md 出现分维度表，不崩

## 实现提示

- rubric 五条的中文名从模块常量 `RUBRIC` 取（`[name for name, _ in RUBRIC]`），
  aggregate 里不要重复硬编码一份键名。
- `_JUDGE_SYSTEM` 是 f-string 拼接，注意 ChatPromptTemplate 的 `{{ }}` 转义（现有代码有先例）。
- 现有测试文件 91 行、6 个测试，先读完再改。

## Answer

已实现（分维度分数 + 一票否决聚合）：

- `src/xiao_wen/eval/judge.py`：`JudgeOutput` 改为 `criteria: dict[str,int]` + `reasons`；
  `JudgeVerdict` 增 `criteria` / `vetoed_by`；新增 `RUBRIC_NAMES` / `VETO_CRITERIA`；
  新增纯函数 `aggregate()`（半进位平均 + 忠实度/合规性 ≤2 一票否决 + 缺维度降级）；
  `judge_once` 改走 `aggregate`；`majority_vote` 携带新字段。
- `scripts/eval/run.py` `_run_judge`：judge_report.md 增分维度均分表（维度/均分/≤2 次数）
  + 明细表「否决」列；judge_samples.jsonl 落 criteria/vetoed_by。
- `tests/test_judge.py`：11 测试全绿（新增 aggregate 5 测试 + judge_once 解析测试改造 +
  majority_vote 两测试适配新字段）。

验证：`pytest tests/test_judge.py` 11 passed；ruff + mypy 对改动文件 0 警告。
