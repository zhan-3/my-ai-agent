# 03 — 差旅统计意图黄金集盲区

**Status:** ready-for-agent
**Blocked by:** None
**Type:** task
**Feature:** agent-eval

## 背景

黄金集「差旅统计」意图 0 样本（`eval_runs/latest/report.md` 混淆矩阵该行全空，精确率/召回率
显示 0.00）。差旅统计是外部插件意图（`plugins/stats.py`），靠注册表自动发现并入词汇表，
但它的意图路由从未被黄金集回归验证过——插件若失效或路由错误，现有评测完全测不出。

## What to build

- 往 `tests/data/intent_golden.jsonl` 加 **8~10 条**「差旅统计」样本
  （字段：input/expected/note 必填，recent/subtasks 可选——与现有 golden 同构，无 id/source）
- 例句方向：「我今年出差几次了」「统计下我常去哪些城市」「我上季度出差多少天」
  「帮我看看差旅画像」等；note 写判定理由
- 跑 `uv run python scripts/eval/run.py --set intent --threshold 1.0`，维持 100%
  （差旅统计样本应被正确路由到「差旅统计」意图）

## 不做

- 不验证 stats.py 产出的画像内容（那是 E2E-02 已覆盖的空态/内容层）
- 不碰混淆矩阵代码

## 验收

- [ ] intent_golden.jsonl 增 8~10 条差旅统计样本，schema 与现有同构
- [ ] `--set intent --threshold 1.0` 100%（需 .env 密钥）
- [ ] 门禁全绿（`scripts/gate.sh`）
