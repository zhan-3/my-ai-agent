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

### Logging

Use the stdlib `logging` for new code: `logging.getLogger("xiao_wen.<module>")`. INFO for key paths; WARNING/ERROR for failures and silent degradations, always naming the reason — never a bare `except: pass`. Keep the `httpx` logger muted (see `stability.py`); logs land in `data/stability.log` (daily rotation, git-ignored) plus stdout.

### Domain guardrails

- **Supervisor runtime:** Production uses a bounded Pi-inspired `decide → call child Agent → observe → decide → final` loop. Preserve registered child Agents as domain executors; do not reintroduce fixed supervisor Workflow branches. Test the Loop interface rather than internal topology.
- **Trip orchestration:** Preserve the existing multi-agent `collect-then-compose` flow inside the itinerary child Agent. Keep domain logic in deep modules and child Agents thin. Policy claims in answers must carry RAG evidence, and weather failures must be represented explicitly rather than filled with guesses.
- **Ticket boundary:** 晓问不生成购票链接、不查询或编造车次/时刻/余票/票价、不代购票、不解析车站；购票与票务查询由商旅平台（travel.xiaowen.com）承担。行程中只建议交通方式（如「高铁」），写「以晓问商旅平台实时查询为准」；不要从旧版 12306 接入找回任何逻辑（已全删）。
- **Trip dates:** 行程日期验证由代码层确定性执行（validation.py / trip_planner）：返程不早于出发、过去日期拦截、用户明确日期优先于默认值。
- **Chroma:** `data/chroma/` is runtime state, not source. Access persistent Chroma through the existing cross-process lock; keep `data/chroma.lock` and `data/chroma.corrupt-*` ignored and never commit local indexes or backups.
- **Configuration:** `.env` takes precedence over inherited shell variables for project settings. Keep the configured model (`deepseek-v4-flash`) unless a user explicitly requests a change; treat transient Pateway 402 errors as an operational issue, not a reason to silently switch models or keys.
