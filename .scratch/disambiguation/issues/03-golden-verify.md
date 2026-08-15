# 03 — 多轮消歧验证与回归

**What to build:** 黄金集补 recent 多轮用例（①/② 回复在上下文下正确消解），跑基线无回退；全量门禁 + 提交。

**Blocked by:** 02

**Status:** resolved

- [ ] 黄金集 +4 条 recent 多轮用例（「②」→ 行程规划、「①」→ 其他、航班+反问上下文）
- [ ] `uv run python scripts/golden_intents.py --threshold 0.95` 通过
- [ ] ruff + pytest -m "not integration" + mypy 全绿

## Answer

已实现并验证：黄金集 +2 多轮用例（79 条 99
## Answer

已实现并验证：黄金集 77→79（+2 消歧多轮用例），基线 99% PASS；ruff/pytest(161)/mypy 全绿。
