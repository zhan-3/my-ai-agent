## Agent skills

### Issue tracker

Issues and specs live as markdown files under `.scratch/<feature>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles map to label strings with matching names: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Before changing domain behavior or architecture, read the relevant glossary in `CONTEXT.md` and ADRs under `docs/adr/`; use their terminology and surface conflicts explicitly. See `docs/agents/domain.md`.

### Quality gate

Before committing code changes, run `scripts/gate.sh`; it executes the deterministic backend gate (Ruff lint, Ruff format check, non-integration pytest, then mypy). Run frontend, real-LLM, evaluation, or image checks only when the corresponding surface changed; see `docs/test-map.md`.

Unit tests use the single Postgres memory backend. Start it with `docker compose up -d postgres` and export `POSTGRES_TEST_URL=postgresql://postgres:123456@localhost:5432/xiao_wen_test` before running tests. Tests refuse to fall back to `POSTGRES_URL`.

### Domain guardrails

- **Supervisor runtime:** Production uses a bounded Pi-inspired `decide → call child Agent → observe → decide → final` loop. Preserve registered child Agents as domain executors; do not reintroduce fixed supervisor Workflow branches. Test the Loop interface rather than internal topology.
- **Trip orchestration:** Preserve the existing multi-agent `collect-then-compose` flow inside the itinerary child Agent. Keep domain logic in deep modules and child Agents thin. Policy claims in answers must carry RAG evidence, and weather failures must be represented explicitly rather than filled with guesses.
- **12306 tickets:** 晓问不生成购票链接、不查询车次/余票/票价、不代购票；购票与票务查询由商旅平台承担。行程中只建议交通方式（如「高铁」），不编造车次或时刻。
- **Ticket dates:** Use the official dynamic sale-until page when available; fallback is 15 days including today (`today + 14 days`). Validate both outbound and return dates, with return date not earlier than outbound. Preserve commas in `fs`, `ts`, and two-date `date` query parameters. The user’s explicit date always wins over defaults.
- **Station ambiguity:** If official station data cannot uniquely resolve a station, return a clarification/error and do not guess a code. City defaults such as `临沂→临沂北` or `北京→北京南` must remain visibly confirmable to the user.
- **Chroma:** `data/chroma/` is runtime state, not source. Access persistent Chroma through the existing cross-process lock; keep `data/chroma.lock` and `data/chroma.corrupt-*` ignored and never commit local indexes or backups.
- **Configuration:** `.env` takes precedence over inherited shell variables for project settings. Keep the configured model (`deepseek-v4-flash`) unless a user explicitly requests a change; treat transient Pateway 402 errors as an operational issue, not a reason to silently switch models or keys.
