# Grant history: codex status

| Task | State | Notes |
|---|---|---|
| G1+G2 | implemented, uncommitted 2026-11-20 | Read-only grant history API/page and three MCP tools; local verification passed. Claude to review and stage. |
| G1b | implemented, uncommitted 2026-11-20 | Grant page layout and labeling fixes after staging review; mocked Chromium layouts checked at 1280 px and 375 px. Claude to review and stage. |

## G1b diary facts — 2026-11-20T00:54:27+00:00

- **Objective:** Fix the grant-history page's expanded-row layout, phone width, source labels, detail presentation, duplicate FON variant, fiscal-year bars, and by-state list after Claude's staging review.
- **Files changed:** `frontend/src/pages/CdcGrantHistory.{jsx,css,test.jsx}`, screenshots in `frontend/screenshots/grant-history-g1b-{1280,375}.png`, and this status file. The walkthrough locator still matches, so its script needed no change.
- **Outcome:** Details use a full-width table row and a two-column definition list that becomes one column on phones. Recipient table widths and a local scroll container keep amounts unwrapped. Source codes have display labels; uppercase address and business-type strings are title-cased for display. The FON excludes self-variants, positive-only bars start at the left, and the state list starts at 10 with a show-all control and separate total/count columns.
- **Verification:** `npm test` passed 180/180; `npm run build` passed; `node --check scripts/beta-walkthrough.mjs` passed; `git diff --check` passed. An initial focused test failed because its abstract-source expectation omitted the visible "Abstract source:" prefix; corrected it and reran successfully.
- **Browser review:** Chromium against a mocked Vite server, with one row expanded, produced the two screenshots. At 1280 px and 375 px, `document.documentElement.scrollWidth` equaled the viewport width; the amount cell computed `white-space: nowrap`. At 375 px, the recipient table's 850 px content scrolls inside a 317 px container. Screenshots were visually inspected.
- **Publication and next action:** No database writes, commit, push, merge, or deploy. Staging and live are unchanged by this task. Claude should review this worktree and deploy staging for the real-data walkthrough.

## G1+G2 diary facts — 2026-11-20T00:43:00+00:00

- **Objective:** Build the CDC NOFO grant-history page and add state funding and grant-history MCP tools under the G1+G2 contract. No database writes, commit, push, merge, or deploy were performed.
- **Files changed:** `backend/app/state_funding/{grant_history,lookup,router}.py`; read-only helpers in `backend/app/funding_report/lookup.py`; `backend/app/mcp_server/{app,tools}.py`; `backend/tests/{test_grant_history_api,test_mcp_state_funding,test_mcp_integration}.py`; `frontend/src/{api/stateFunding.js,main.jsx,utils/routeResolver*,pages/CdcGrantHistory*,pages/CdcStateFundingProfile*}`; `frontend/scripts/beta-walkthrough.mjs`; this status file.
- **Lookup timing on places_staging:** `OT202004` 346 awards, 0.083 s; `PS212102` 97 award rows, 0.057 s. The latter's latest funded year is FY2026, with $10,166,689.00 total; top states TX $1,214,576, FL $1,130,952, CA $1,104,148.
- **MCP response sizes:** `get_state_funding('CA', 2026)` 11,048 bytes; `list_state_grants('CA', 2026, limit=100)` 49,917 bytes and 63 returned rows; `get_grant_history('OT202004', limit=100)` 49,595 bytes and 93 returned rows. Both capped pages carry `truncated` and `next_offset`.
- **State-page q check:** `q=CDC-RFA-PS21-2102` returned only `PS212102` awards and matched the grant-history latest-FY state totals across all 34 funded states; no change to the state search rule was needed.
- **Verification:** state funding and grant-history backend tests 19 passed; MCP unit, integration, and new state funding tests 28 passed using a temporary ignored local venv symlink, then removed; frontend `npm test` 176 passed, `npm run build` passed, and `node --check scripts/beta-walkthrough.mjs` passed. The deployed browser walkthrough remains for Claude after staging deploy.
- **Contract resolution:** the 50,000-byte MCP cap can be reached before a requested 100-row page is full. The tools keep totals and complete state/year summaries, return the largest fitting contiguous award page, and expose `next_offset` for continuation. Grant-history awards retain per-year history while optional fields are removed when needed.
- **Status and next action:** code exists only in this Codex worktree; staging and live are unchanged. Claude should review the diff, run the deployed walkthrough and audit, then present Gate A for John.
