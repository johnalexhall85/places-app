# Task M1 (Codex): CDC state funding map

Assigned by Claude on 2026-11-20. Work in `/home/john/chip-codex-state` on branch `codex/state-map`, which starts at `claude/state-map` (beta `81965f4` plus the plan and contract).

- **Database:** `backend/.env` points at `places_staging`, which has an active `state_funding` build.
- **Backend tests:** `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_state_map_api.py tests/test_state_funding_*`
- **Frontend:** `cd frontend && npm install d3-geo && npm test && npm run build`.

**You own:** `backend/app/state_funding/**`, `backend/tests/test_state_map_*` and `backend/tests/test_state_funding_*` (except `test_state_funding_audit.py` and `test_state_map_audit.py`), `frontend/**`, and `docs/state-map/status/codex.md`.

**Rules:**
- Do not commit, push, merge, deploy, or use sudo. Write no database rows.
- Do not edit migrations, `backend/app/area_pilot/**`, `backend/app/community/**`, `backend/app/mcp_server/**`, or `docs/beta/contract-examples`.
- **Never edit `docs/PROJECT_DIARY.md` or the handbook.** Diary facts go in your status file.
- **Write normally formatted source:** JSX broken across lines, unminified CSS, and Python lines of about 120 characters or fewer, as in the existing files.
- Existing state funding and grant history endpoints and pages must not change behavior, apart from the "National map" links.

## Read first

1. [PLAN.md](../PLAN.md) and the whole of [CONTRACT.md](../CONTRACT.md). This is the specification.
2. [State funding contract](../../state-funding/CONTRACT.md) with Amendments 1–2, and the current `backend/app/state_funding/{lookup,router}.py`.
3. `backend/app/area_pilot/lookup.py`: `area_info` and `states` only (read, do not edit).
4. `frontend/src/pages/CdcStateFundingProfile.{jsx,css}`: the new page must look like its sibling (tokens, header, KPI tiles, source lines, controls).

## Steps

1. Lookup and the two routes (contract §1–§2). Register `/map/shapes` before anything that could capture it. Record the response sizes and timings for FY2026 in your status file.
2. The page (contract §3).
3. Tests and the walkthrough step (contract §4).
4. Screenshot the page yourself if you can (for example with the walkthrough's Playwright setup against `npm run dev` with mocked or staging data) at 1280 and 375 px and fix anything cramped, overlapping, or scrolling sideways.

## Report

Update `docs/state-map/status/codex.md`: files changed, test commands and counts, sizes and timings, anything in the contract you could not meet and why, and open questions. Then stop.
