# Task G1+G2 (Codex): grant history page and state funding MCP tools

Assigned by Claude on 2026-11-20. Work in `/home/john/chip-codex-state` on branch `codex/grant-history`, which starts at `beta` `b300a56`.

- **Database:** `backend/.env` points at `places_staging`, which has active `state_funding` and `funding_report` builds.
- **Backend tests:** `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest ...`
- **MCP tests:** `PYTHONPATH=. /home/john/chip-claude/backend/.venv-mcp/bin/python -m pytest tests/test_mcp_*`
- **Frontend:** `cd frontend && npm test` and `npm run build`.

**You own:**
- `backend/app/state_funding/**`
- read-only helpers added to `backend/app/funding_report/lookup.py` (do not touch the builder)
- `backend/app/mcp_server/**`
- `backend/tests/test_state_funding_*` and `backend/tests/test_grant_history_*`, except `test_state_funding_audit.py` and `test_grant_history_audit.py`
- `backend/tests/test_mcp_*`
- `frontend/**`
- `docs/grant-history/status/codex.md`

**Rules:**
- Do not commit, push, merge, deploy, or use sudo.
- Write no database rows. No build is needed.
- Do not edit migrations, `backend/app/community/**`, `docs/beta/contract-examples`, or the MCP eval files.
- **Never edit `docs/PROJECT_DIARY.md` or the handbook.** Diary facts go in your status file.
- **Write normally formatted source:** JSX broken across lines, unminified CSS, and Python lines of about 120 characters or fewer, as in the existing files.

## Read first

1. [PLAN.md](../PLAN.md) and the whole of [CONTRACT.md](../CONTRACT.md). This is the specification.
2. [Tool contract](../../mcp/TOOL_CONTRACT.md): the envelope, the size cap, errors, and Amendments 3 and **4**.
3. [State funding contract](../../state-funding/CONTRACT.md) with Amendments 1–2, and the current `backend/app/state_funding/{lookup,router}.py`.
4. `backend/app/funding_report/lookup.py` (`resolve_nofo`, `_rows`, `_subaward_block`) and `keys.py`.
5. `backend/app/mcp_server/tools.py`: follow `get_nofo_overview` and `_funding_envelope`.
6. `frontend/src/pages/CdcStateFundingProfile.{jsx,css}`. The new page must look like its sibling: the same tokens, header, KPI tiles, source lines, and expandable rows. `frontend/src/community/` has the small chart style (`IndicatorChart`) to follow for the per-year bars.

## Part A: grant history (G1)

1. Lookup per contract §2: `grant_history` and `grant_award` in `app/state_funding/lookup.py` (or a new `grant_history.py` in that package), plus the two `funding_report.lookup` helpers. Use set-based SQL. A 346-award NOFO (`OT202004`) must return in under 1 s on staging; record the timing.
2. Router per §3: add the three routes to the existing `/state-funding/v1` router. Register `/grants/{nofo}.csv` so it is not captured by `/grants/{nofo}`.
3. Page per §4:
   - Files: `frontend/src/pages/CdcGrantHistory.{jsx,css,test.jsx}`, plus API functions in `frontend/src/api/stateFunding.js`.
   - Route `/cdc-funding/grant/{nofo}`, added to `utils/routeResolver.js` and `main.jsx`.
   - The state-page links per §5.
4. Tests:
   - **Backend** (`tests/test_grant_history_api.py`): the latest-FY rule, including the all-non-positive case; split-state grouping; past-award state; the recipient-type fallback order; 404 with suggestions; CSV shape and filename; `q=CDC-RFA-PS21-2102` on the state grants endpoint (§5). Add one staging test that skips when the database is unreachable: PS212102 latest-FY state totals sum to `totals.latest_fy.total`.
   - **Vitest:** render with mocked data; grouping and state totals; search; sort; the past toggle; lazy expand; a negative amount shown with its sign; the canonical-URL replace; the state-page link.
5. Update `frontend/scripts/beta-walkthrough.mjs`:
   - visit `/cdc-funding/grant/CDC-RFA-PS21-2102`;
   - check the heading;
   - check that a state group exists;
   - expand one row;
   - check the 375 px width has no page overflow.

   Run `node --check`. Claude runs the walkthrough against staging after deploying.

## Part B: MCP tools (G2)

1. Add `get_state_funding`, `list_state_grants`, and `get_grant_history` per Amendment 4, with typed Pydantic returns, the shared annotations, sources, the interpretation rules, the cache fingerprint, and the server-instructions sentence. The tools call only `app.state_funding.lookup`.
2. Check that `import app.state_funding.lookup` works in `/home/john/chip-claude/backend/.venv-mcp`. If it does not, fix the import inside `app/state_funding` (Amendment 4 §1).
3. Tests in `tests/test_mcp_state_funding.py`:
   - the argument validation and errors;
   - a state given as a name and as a FIPS code;
   - paging;
   - every tool's response under 50,000 bytes for CA FY2026, `list_state_grants` with `limit=100`, and `get_grant_history("OT202004", limit=100)`;
   - the existing MCP tests still pass, with the tool count now 14.

## Done when

- Every backend, MCP, and frontend test passes, and `npm run build` passes.
- `docs/grant-history/status/codex.md` has a row for G1+G2 and a section `## G1+G2 diary facts — <ISO timestamp with timezone>`. That section lists:
  - the files changed;
  - the commands and their results;
  - the timings for `OT202004` and PS212102;
  - the PS212102 `latest_fy`, latest-FY total, and top three states;
  - the response sizes of the three tools;
  - the §5 `q` check result;
  - any contract ambiguity you resolved, and how.
- `git status` shows changes only in your owned paths.

Finish with a report of 10 lines or fewer.
