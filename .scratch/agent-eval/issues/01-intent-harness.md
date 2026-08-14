# eval-01 — 意图分类评测 harness（第一层：规则层）

**What to build:** 评估系统第一层落地——意图分类评测并入统一 harness，
出**混淆矩阵**（黄金脚本没有的跨意图错分视图）+ 每意图 精确率/召回率/F1 + 落盘产物。

**范围（严格第一层，不越界）**：
- `src/xiao_wen/eval/metrics.py`：纯函数（混淆矩阵 / 每意图指标 / 错误提取），pytest 可引用
- `scripts/eval/run.py`：`--set intent --threshold 0.95 [--verbose]`，读 `tests/data/intent_golden.jsonl`
  （暂不迁移——golden_intents.py 挂 CI 不能动；第二层 tools 集落地时再建 tests/data/eval/）
- 落盘 `eval_runs/latest/`：`metrics.json` + `errors.jsonl` + `report.md`（含混淆矩阵表）
- 退出码：accuracy < threshold → 1（对齐 golden_intents.py 语义）

**不做**：judge 层（LLM）、trace 录制（第四层再做）、数据文件迁移、golden_intents.py 改造。

**Blocked by:** None

**Status:** ready-for-agent

- [ ] metrics.py 纯函数 + 单测（混淆矩阵形状/每意图指标/错误提取）
- [ ] scripts/eval/run.py CLI（--set/--threshold/--verbose，落盘三件套，退出码）
- [ ] 实跑黄金集 79 条，100% 全绿
- [ ] 门禁全绿

## Answer

已实现并验证：意图层评测 harness 落地（规则层，无 LLM）。
- src/xiao_wen/eval/metrics.py：混淆矩阵 / 每意图精确率·召回率·F1 / 错误提取（5 单测）
- scripts/eval/run.py --set intent：读黄金集 79 条 → eval_runs/latest/{metrics.json, errors.jsonl, report.md}
- 实跑 100% PASS；golden_intents.py（CI 挂载）未动；数据文件暂留原位，第二层落地时迁 tests/data/eval/
- 门禁全绿
