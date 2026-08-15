# 03 — 多数票降本（N=1 默认）+ 考官考生同源阻断开关

**Status:** resolved
**Blocked by:** None（与 #02 可并行；改动面与 #01 无冲突）
**Type:** task

## 背景

1. judge 用 temperature=0 + 同用例 N=3 多数票。temp=0 下三次调用结果几乎恒同
   （judge.py docstring 自认「方差来自模型自身漂移」）——2/3 的 token 花在不产生
   信息的地方。多数票的正确形态是跨模型或非零温度，都不在当前实现里。
2. judge 模型独立 env（`EVAL_JUDGE_*`）设计了但实际没配，一直回退 `DEEPSEEK_*`
   （考官=考生同模型，judge_report.md 可见）。同源偏差只被标注、没被阻断。

## What to build

### 1. `scripts/eval/run.py`

- `--judge-n` 默认值 3 → **1**。help 文案注明：「temp=0 下多次投票几乎恒同，
  仅在配置了独立高方差 judge 或诊断漂移时才需要 >1」。
- 新增 `--require-independent-judge` 开关：置位且 `judge.judge_env_used()` 返回
  回退来源时，打印错误并 **exit 2**（与准确率不达标的 exit 1 区分开）。
- 未置位但处于回退时，把现有一行标注升级为显眼告警块（stderr）：

```
⚠️  judge 回退 DEEPSEEK_*：考官=考生同模型，分数存在同源偏差（自评倾向）。
    配置 EVAL_JUDGE_MODEL / EVAL_JUDGE_BASE_URL / EVAL_JUDGE_API_KEY 消除。
```

  并在 judge_report.md 头部加同样的告警行（已有「模型：」行，紧随其后）。

### 2. `src/xiao_wen/eval/judge.py`

- `judge_env_used()` 之外补一个布尔便捷函数 `is_judge_independent() -> bool`
  （run.py 判断用，不再解析字符串）。
- docstring 更新：删除/改写「同用例 N 次多数票」段落为当前语义
  （默认单次；多数票留作跨模型/高方差 judge 的扩展点）。
- `judge_with_votes` 保留（金丝雀和未来跨模型都用它），仅默认参数 `n: int = 3` → `n: int = 1`。

### 3. 测试

- `tests/test_judge.py` 加 `test_is_judge_independent`（monkeypatch os.environ 两种状态）
- run.py 的 CLI 行为（exit 2）不强求自动化测试；在票的 `## Answer` 里贴一次手动
  验证输出即可（无 EVAL_JUDGE_* 环境 + `--require-independent-judge` → exit 2）

### 4. 文档

- `.env.example` 补三行 `EVAL_JUDGE_MODEL/BASE_URL/API_KEY` 注释占位（若尚无）
- README 的评测章节（若提到 judge）同步 N 默认值说明；没提就不加

## 不做

- 跨模型投票实现
- CI 接入（另开票）

## 验收

- [ ] `uv run pytest tests/test_judge.py -q` 全绿；门禁四步全绿（`scripts/gate.sh`）
- [ ] 手动验证 exit 2 路径并贴输出
- [ ] （有密钥时）`--with-judge --judge-sample 2` 实跑：默认单次调用（日志确认无 ×3），
      报告含告警行

## Answer

已实现并验证：

- `judge_with_votes(n=1)` 默认单次；docstring 改写（temp=0 下多次投票几乎恒同，
  多数票留作跨模型/高方差 judge 扩展点）。
- `is_judge_independent()`：EVAL_JUDGE_MODEL/BASE_URL/API_KEY 三变量齐备才算独立，
  与 `get_judge_llm` 的逐项回退语义一致；`judge_env_used()` 改用它（修掉原来只看
  API_KEY 的不一致）。
- run.py：`--judge-n` 默认 3→1；新增 `--require-independent-judge`（回退时 exit 2，
  与准确率不达标的 exit 1 区分）；回退时 stderr 告警块 + judge_report.md 头部告警行。
- `.env.example` 补 EVAL_JUDGE_MODEL/BASE_URL/API_KEY 三行注释。
- 测试：`test_is_judge_independent`（三变量齐/缺两种状态）+ `test_judge_env_used_marks_source`。

手动验证：

```
$ uv run python scripts/eval/run.py --judge-canaries --require-independent-judge
错误：--require-independent-judge 但未配置独立考官（EVAL_JUDGE_* 三变量不全）
⚠️  judge 回退 DEEPSEEK_*：考官=考生同模型，分数存在同源偏差（自评倾向）。
    配置 EVAL_JUDGE_MODEL / EVAL_JUDGE_BASE_URL / EVAL_JUDGE_API_KEY 消除。
（退出码 2）
```

`--with-judge --judge-sample 2` 实跑：`judge 层：2 条行程规划样本 ×单次判定`（日志确认无 ×3），
报告头部含同源偏差告警行。门禁四步 + 黄金集 84/84 全绿。

### 追加（补标准·第 1 步，用户拍板「做」）

- 独立考官升级为**默认硬阻断**：judge 层未配 EVAL_JUDGE_* 三变量即 exit 2，不再静默回退；
  `--require-independent-judge` 变默认行为（保留兼容），新增 `--allow-judge-fallback`
  显式放行（仅本地调试）。
- `.env.example` 写明考官推荐 **Qwen**（dashscope OpenAI 兼容端点，复用 DASHSCOPE_API_KEY），
  与考生 DEEPSEEK_* 不同家。
- 验证：无配置 `--judge-canaries` → exit 2 含指引；`--allow-judge-fallback` → 放行告警；
  `is_judge_independent()` 三变量齐 → True。
