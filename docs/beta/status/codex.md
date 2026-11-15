# Codex status: product track

Read with [the execution plan](../EXECUTION_PLAN.md). Codex updates this file at the end of every work package.

| Package | State | Branch | Notes |
|---|---|---|---|
| X1 Community API | Done; merged and deployed to staging | `codex/beta-x1-community-api` | Staging `beta` at `6f76e0d`; authenticated Nginx reads passed for catalog, search, county profile, comparison, facilities, topics, tract route, and CSV. Local focused tests: 13 passed. Full suite: 655 passed, two unrelated source-dependent failures with ignored inputs absent; the known FY2026 source mismatch remains when inputs are linked. |
| X2 Landing, navigation, county profile, brand tokens | Done; merged and deployed to staging | `codex/beta-x2-landing-profile` | Staging `beta` was at `8cd7412` after X2. Root landing, `/explore/map` legacy route, county profile, brand tokens. Frontend 144/144 tests and Vite build passed; authenticated desktop/mobile browser walkthrough passed with 28 Person County cards, seven topic tiles, no page errors or horizontal overflow. X4 later connected topic cards to topic pages. |
| X3 Comparison and PDF export | Done; merged and deployed to staging | `codex/beta-x3-comparison-pdf` | Three-showcase comparison renders 28 aligned indicators through authenticated Nginx, with no page errors or document overflow at 390 px. PDF endpoint reuses Playwright profile rendering with the current demo session cookie; 200 response, 9-page PDF, source and income text verified. Backend 656 tests passed with two unrelated source-dependent cases deselected; frontend 146/146 and build passed. |
| X4 Topics and tract patterns | Done; merged and deployed to staging | `codex/beta-x4-topics-tracts` | Seven API-driven topic pages and source-map measure preselection; profile displays ACS published tract shapes and an explicit PLACES empty state until a combined release is active. Frontend 147/147 and build passed. Authenticated desktop/mobile browser checks passed. |
| X5 District briefing | Done; merged and deployed to staging | `codex/beta-x5-district-briefing` | WV-01 API and page show seven Census district estimates, mapped facilities, and 28 named overlapping counties; state/district picker and ACS community source map support 119th Congress geography. C1/C2 measures are in topics and county profiles; the two insurance definitions are visibly distinct. HRSA Details pointer clicks passed at 1365 and 390 px. Staging documentation follow-up merged at `4153aae`. |
| X6 End-to-end tests and polish | Done; merged and deployed to staging; Gate 3 review pending | `codex/beta-x6-gate3` | The authenticated walkthrough covers 46 indicators in each showcase county, PLACES and ACS Person tracts, topics, comparison/PDF, district briefing and source map, legacy routes, pointer clicks, keyboard and mobile layout, and sampled contrast. Frontend 149/149 and build passed. Seven images and 47 archived-source checks cover eight products plus WV-01. Mapped facility counts now cite their source release. Final code is on staging `beta` at `c714d3c` before this documentation follow-up. |

## What Claude can rely on now

- The community API, new pages, source maps, and exports are available through staging Nginx. A staging-only access code is stored outside the repository at `/home/john/.local/share/chip/staging-beta-access-code` (mode 600); John can retrieve it on the VM for review.
- Seven topics include C1 PLACES and C2 ACS measures. Person County's profile presents 46 published indicators and seven source-published tracts for both ACS and PLACES diabetes. WV-01 uses Census-published district estimates; county profiles remain context.
- Gate 3 product review is ready on staging. The concise route checklist, seven screenshots, and the 47-check release-pinned source report are under `deliverables/beta/`. No live promotion was made.

## Gate 3 and remaining work

- John reviews the specific staging `beta` commit at Gate 3 before any live promotion. The promotion runbook requires a fresh live recovery set, digest-matched ingest, live-appropriate PDF frontend URL, and separate approval. The existing Gate 1 source report remains historical; the Gate 3 report is tied to current staging pointers and must be rerun if they change.
- The full backend suite has one known unrelated FY2026 funding source natural-key mismatch (676 passed, one failed in the X5 run). No product or data-track staging work remains open in this status.

## BRFSS and state profiles (plan approved 2026-11-15; section added by Claude as the plan directs)

Read with [the BRFSS and state plan](../BRFSS_STATE_PLAN.md). Codex updates this table.

| Package | State | Branch | Notes |
|---|---|---|---|
| Y1 Community API: state profile, state search, exports, BRFSS companion | Done; merged and deployed to staging | `codex/brfss-y1-community-api` | Lookup-only state search/profile, 33-row state CSV, PDF route, and 13 paired BRFSS rows on Person County response. Authenticated staging API checks and 232 area/community tests passed. Y2 verified the rendered PDF. |
| Y2 State profile page | Done; merged and deployed to staging | `codex/brfss-y2-state-profile` | State page has 33 source-published indicator cards, 20 BRFSS rows, facilities, county/district links, funding link, CSV and PDF. North Carolina and Kentucky page checks passed; North Carolina PDF is seven pages with source and limits text. Route test and Vite build passed. Code at `c1569a1`; documentation follow-up in this branch. |
| Y3 County profile and comparison changes | Not started | | |
| Y4 BRFSS state map and topics | Not started | | |
| Y5 Landing, walkthrough, evidence | Not started | | |
