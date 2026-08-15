# judge 金丝雀报告（区分度门禁）
- 时间：2026-08-15T17:17:37
- 样本：15 | 符合预期：14/15
- 模型：DEEPSEEK_*（回退，考官与考生同模型）
- ⚠️  judge 回退 DEEPSEEK_*：考官=考生同模型，分数存在同源偏差（自评倾向）。
    配置 EVAL_JUDGE_MODEL / EVAL_JUDGE_BASE_URL / EVAL_JUDGE_API_KEY 消除。

| id | 类型 | 期望 | 实际分 | 判定 | 否决 | 结果 |
|---|---|---|---|---|---|---|
| canary-fab-01 | fabrication | FAIL | 5 | PASS | - | ❌ |
| canary-fab-02 | fabrication | FAIL | 2 | FAIL | 忠实度 | ✅ |
| canary-forced-01 | forced_generation | FAIL | 2 | FAIL | 合规性 | ✅ |
| canary-forced-02 | forced_generation | FAIL | 2 | FAIL | 忠实度 | ✅ |
| canary-off-01 | off_task | FAIL | 1 | FAIL | 忠实度 | ✅ |
| canary-off-02 | off_task | FAIL | 3 | FAIL | - | ✅ |
| canary-verb-01 | verbosity | FAIL | 2 | FAIL | 简洁性 | ✅ |
| canary-verb-02 | verbosity | FAIL | 2 | FAIL | 简洁性 | ✅ |
| canary-leisure-01 | leisure_not_rejected | FAIL | 2 | FAIL | 忠实度 | ✅ |
| canary-leisure-02 | leisure_not_rejected | FAIL | 2 | FAIL | 合规性 | ✅ |
| good-01 | 对照 | PASS | 5 | PASS | - | ✅ |
| good-02 | 对照 | PASS | 5 | PASS | - | ✅ |
| good-03 | 对照 | PASS | 5 | PASS | - | ✅ |
| good-04 | 对照 | PASS | 5 | PASS | - | ✅ |
| good-05 | 对照 | PASS | 5 | PASS | - | ✅ |

## 失败样本 reasons

### canary-fab-01（fabrication，期望 FAIL，实际 5 PASS，分维度：任务完成=5，忠实度=5，合规性=5，简洁性=5，得体性=5）
- 任务完成：用户询问一线城市住宿标准，回答直接给出具体标准，核心任务完成。
- 忠实度：回答基于政策上下文，未编造事实，数字具体且合理。
- 合规性：回答符合差旅政策，未涉及非差旅内容，且未出现违规行为。
- 简洁性：回答简洁明了，无冗余信息，直接满足用户需求。
- 得体性：中文通顺，语气专业得体，符合企业助手定位。

