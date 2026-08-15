## Agent skills

### Issue tracker

Issues and specs live as markdown files under `.scratch/<feature>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles map to label strings with matching names: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Quality gate

Before committing code changes, run the gate checks in this order (fast first):
`uv run ruff check src tests plugins scripts` → `uv run ruff format --check src tests scripts` → `uv run pytest -m "not integration"` → `uv run mypy src/xiao_wen tests scripts`.
Unit tests need Postgres (single memory backend): `docker-compose up -d postgres` + `export POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test`.

本地一键跑法：`scripts/gate.sh`（同序四步）；`--integration`/`--golden`/`--full` 追加集成测试与黄金集回归（真 LLM，需 .env 密钥）。

修改 `intent.py` 分类相关代码时，额外跑 `uv run python scripts/eval/run.py --set holdout` 附分数（防规则过拟合，见 `tests/data/HOLDOUT.md`）。
