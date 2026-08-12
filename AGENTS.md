## Agent skills

### Issue tracker

Issues and specs live as markdown files under `.scratch/<feature>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles map to label strings with matching names: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Quality gate

Before committing code changes, run the gate checks in this order (fast first):
`uv run ruff check src tests plugins scripts` → `uv run pytest -m "not integration"` → `uv run mypy src/xiao_wen`.
The full delivery gate (`python scripts/delivery.py gate`) additionally runs integration tests and smoke, and requires `.env` + network.
