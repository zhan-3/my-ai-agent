## Agent skills

### Issue tracker

Issues and specs live as markdown files under `.scratch/<feature>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles map to label strings with matching names: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Before changing domain behavior or architecture, read the relevant glossary in `CONTEXT.md` and ADRs under `docs/adr/`; use their terminology and surface conflicts explicitly. See `docs/agents/domain.md`.

### Quality gate

Before committing code changes, run `scripts/gate.sh`; it executes the fast-first unit gate (Ruff lint, Ruff format check, non-integration pytest, then mypy). Use `--integration`, `--golden`, or `--full` only when the corresponding real-LLM checks are required and `.env` has valid credentials.

Unit tests use the single Postgres memory backend. Start it with `docker-compose up -d postgres` and export `POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test` before running tests. The test setup falls back to `POSTGRES_URL` when this variable is absent and may clear that database, so always point tests at the dedicated test database.

When changing intent classification in `src/xiao_wen/intent.py`, also run `uv run python scripts/eval/run.py --set holdout` and report the score; see `tests/data/HOLDOUT.md`.

### Domain guardrails

- **Trip orchestration:** Preserve the existing multi-agent `collect-then-compose` flow. Keep domain logic in deep modules; agents should remain thin adapters. Policy claims in answers must carry RAG evidence, and weather failures must be represented explicitly rather than filled with guesses.
- **12306 tickets:** Use only the public official railway entry. Station names/codes come from `src/xiao_wen/stations.py` and the official `station_name.js`; link construction and date validation stay in `src/xiao_wen/ticket_link.py` and `src/xiao_wen/ticket_policy.py`. Return official links and clearly bounded policy facts—not invented trains, schedules, availability, fares, orders, or purchase results, and never private ticket APIs.
- **Ticket dates:** Use the official dynamic sale-until page when available; fallback is 15 days including today (`today + 14 days`). Validate both outbound and return dates, with return date not earlier than outbound. Preserve commas in `fs`, `ts`, and two-date `date` query parameters. The user’s explicit date always wins over defaults.
- **Station ambiguity:** If official station data cannot uniquely resolve a station, return a clarification/error and do not guess a code. City defaults such as `临沂→临沂北` or `北京→北京南` must remain visibly confirmable to the user.
- **Chroma:** `data/chroma/` is runtime state, not source. Access persistent Chroma through the existing cross-process lock; keep `data/chroma.lock` and `data/chroma.corrupt-*` ignored and never commit local indexes or backups.
- **Configuration:** `.env` takes precedence over inherited shell variables for project settings. Keep the configured model (`deepseek-v4-pro`) unless a user explicitly requests a change; treat transient Pateway 402 errors as an operational issue, not a reason to silently switch models or keys.
