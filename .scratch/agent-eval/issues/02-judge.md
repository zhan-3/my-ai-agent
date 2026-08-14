# 票 #02：judge 层（layer 3，LLM-as-judge）

**Status**: resolved
**Blocked by**: #01（trace 已就绪，judge 输入 = trace 事件链）

## 范围（spec D4）

- `src/xiao_wen/eval/judge.py`：rubric 五条（任务完成/忠实度/合规性/简洁性/得体性，
  从 CONTEXT.md 领域规则提炼），输出 `{score:1-5, reasons, verdict}`，
  temperature=0 + json_mode；截断策略只留 input/classify/agent/final 关键段
  （省 token + 防上下文泄漏）。
- judge 模型独立 env（`EVAL_JUDGE_MODEL/BASE_URL/API_KEY`，`llm.get_judge_llm`），
  缺省回退 `DEEPSEEK_*`（同模型降级，报告标注来源）；同用例 N 次多数票
  （score 众数，平局取高）。
- `scripts/eval/run.py --with-judge`：黄金集行程规划样本真跑 chat（trace 落盘）→
  judge 打分 → judge_report.md + 10% 人工复核样本 judge_samples.jsonl。

## Answer

已实现并验证（tdd：5 测试红 → 绿）：

- `judge.py`：RUBRIC 五条、`JudgeVerdict`、`build_judge_input`（截断）、
  `judge_once`（prompt → json_mode 结构化输出，解析失败降级 score 0 不崩）、
  `majority_vote`（众数/平局取高）、`judge_with_votes`、`judge_env_used`（来源日志）
- `llm.py` +`get_judge_llm`（EVAL_JUDGE_* 优先，回退 DEEPSEEK_*；override 测试注入）
- `run.py` +`--with-judge/--judge-n/--judge-sample` + `_run_judge`（真跑 chat + 打分 +
  报告 + 人工复核样本）
- 测试 `tests/test_judge.py`（5 个）：rubric 五条、截断剔除噪音、多数票众数/平局、
  单次解析、假模型注入不烧 token

验证：门禁全绿；真 LLM 冒烟 3 条行程规划样本 × 1 票——3/4/3（缺项追问合规但
任务未完成 → 3 分是正常判断），报告含逐条理由；模型来源正确显示 DEEPSEEK_* 回退。
多数票单票波动（同场景 3 vs 4）正是 n=3 要平滑的方差。
