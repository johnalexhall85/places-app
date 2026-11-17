# Codex status: historical periods

Updated at the end of each task. Claude reads this file before reviewing.

| Package | State | Branch | Notes |
|---|---|---|---|
| H4 year dropdown on `/area/*` | Implemented, uncommitted; awaiting Claude review and staging history publication | `codex/history` | `frontend/src/pages/Places2025Pilot.jsx` and `Places2025Pilot.test.jsx`: period and release selection, URL state, request/cache/shape keys, period-aware labels and notes, geography fallback, selected GEOID across years. 167/167 frontend tests, Vite build, and `git diff --check` passed. |

## H4 diary facts — 2026-11-17T17:39:13+00:00

- **Objective and outcome:** Added the Year select to the shared area map controls, including the mobile drawer. It uses catalog periods, disables unavailable years, keeps a supported year on measure changes, and loads each selected period's release for map, legend, and table. Historical boundary and colour cautions, unmatched-boundary count, district fallback, and selected-area no-shape message are shown. County, state, and district profiles and `TractPatternMap` were not changed.
- **Files and verification:** Only the two frontend files above and this status file changed. Mocked history responses cover three requests, cache separation for two years sharing one release, URL load/round-trip, disabled years, geography fallback, and persistent selection. `npm test` passed 167 tests across 23 files; `npm run build` passed with the existing large-chunk warning; `git diff --check` passed. An initial focused run had three test-fixture failures (wrong default measure and out-of-view focus box); the fixtures were corrected and the focused run passed 33/33.
- **Publication and next action:** No dataset, release, migration, database, service, deployment, commit, or push changed. Historical releases are not yet published on staging, so this was not verified against a running history API. Claude should review and test after publishing CMS GV history. The handbook and project diary were not edited because the H4 task restricts Codex writes to `frontend/**` and this status file; fold these facts into the Claude-owned documents.
- **Backend requests to Claude:** `history_api.periods_for` currently returns only the latest period when no history release exists, so the Year menu cannot show earlier disabled options before the first publication. Please expose declared earlier periods with `available: false` and `release_id: null` until published. Also check whether history table rows with published values but no matching boundary should be included as `boundary_not_comparable` as the source specification says; the current history table query starts from boundary shapes and omits those rows.
