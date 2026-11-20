# Grant history: codex status

| Task | State | Notes |
|---|---|---|
| G1+G2 | implemented, uncommitted 2026-11-20 | Read-only grant history API/page and three MCP tools; local verification passed. Claude to review and stage. |

## G1+G2 diary facts — 2026-11-20T00:43:00+00:00

- **Objective:** Build the CDC NOFO grant-history page and add state funding and grant-history MCP tools under the G1+G2 contract. No database writes, commit, push, merge, or deploy were performed.
- **Files changed:** `backend/app/state_funding/{grant_history,lookup,router}.py`; read-only helpers in `backend/app/funding_report/lookup.py`; `backend/app/mcp_server/{app,tools}.py`; `backend/tests/{test_grant_history_api,test_mcp_state_funding,test_mcp_integration}.py`; `frontend/src/{api/stateFunding.js,main.jsx,utils/routeResolver*,pages/CdcGrantHistory*,pages/CdcStateFundingProfile*}`; `frontend/scripts/beta-walkthrough.mjs`; this status file.
- **Lookup timing on places_staging:** `OT202004` 346 awards, 0.083 s; `PS212102` 97 award rows, 0.057 s. The latter's latest funded year is FY2026, with $10,166,689.00 total; top states TX $1,214,576, FL $1,130,952, CA $1,104,148.
- **MCP response sizes:** `get_state_funding('CA', 2026)` 11,048 bytes; `list_state_grants('CA', 2026, limit=100)` 49,917 bytes and 63 returned rows; `get_grant_history('OT202004', limit=100)` 49,595 bytes and 93 returned rows. Both capped pages carry `truncated` and `next_offset`.
- **State-page q check:** `q=CDC-RFA-PS21-2102` returned only `PS212102` awards and matched the grant-history latest-FY state totals across all 34 funded states; no change to the state search rule was needed.
- **Verification:** state funding and grant-history backend tests 19 passed; MCP unit, integration, and new state funding tests 28 passed using a temporary ignored local venv symlink, then removed; frontend `npm test` 176 passed, `npm run build` passed, and `node --check scripts/beta-walkthrough.mjs` passed. The deployed browser walkthrough remains for Claude after staging deploy.
- **Contract resolution:** the 50,000-byte MCP cap can be reached before a requested 100-row page is full. The tools keep totals and complete state/year summaries, return the largest fitting contiguous award page, and expose `next_offset` for continuation. Grant-history awards retain per-year history while optional fields are removed when needed.
- **Status and next action:** code exists only in this Codex worktree; staging and live are unchanged. Claude should review the diff, run the deployed walkthrough and audit, then present Gate A for John.
