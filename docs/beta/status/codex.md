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
| Y2 State profile page | Done; merged and deployed to staging | `codex/brfss-y2-state-profile` | State page has 33 source-published indicator cards, 20 BRFSS rows, facilities, county/district links, funding link, CSV and PDF. North Carolina and Kentucky page checks passed; North Carolina PDF is seven pages with source and limits text. Route test and Vite build passed. |
| Y3 County profile and comparison changes | Done; merged and deployed to staging | `codex/brfss-y3-county-companion` | Each paired PLACES county card and comparison cell shows the direct state BRFSS estimate, year, CI, and source. County CSV carries paired fields; profile links to its state. Person County has 13 companions on page and CSV; two-county comparison has 26; 13-page PDF contains the label and source. Kentucky has 12 `not_published` and one dental companion. Area/community tests 233 passed. Code at `21e11f7`. |
| Y4 BRFSS state map and topics | Done; merged and deployed to staging | `codex/brfss-y4-state-map` | `/area/brfss` stays at state geography for all zooms; 52 state shapes/rows, source status, CI and response count, fixed legend, and correctly labelled median of states and DC. All 20 BRFSS measures appear in health/prevention topics with preselected map links. Source selectors include BRFSS. Map/route tests 28 passed; staging browser check passed. Code at `5edec8c`. |
| Y5 Landing, walkthrough, evidence | Done; merged and deployed to staging | `codex/brfss-y5-evidence` | Landing search and example include states. Authenticated walkthrough covers state profile, PDF, Kentucky missing status, BRFSS map, and mobile. Refreshed 11 screenshots and 59 release-linked source checks, including four BRFSS measures in each of three states. Frontend 150 tests, backend area/community 233 tests, Vite build, staging walkthrough and source audit passed. Code at `8643f8f`, polish at `9d9069f`. |

All Y packages are on staging. Product track waits at Gate 3 for John's review of the final local `beta` commit reported in the handoff. B4 live promotion belongs to Claude after that approval; Codex made no live changes.

## Public beta TLS handoff (2026-11-16)

At John's request, system Nginx now serves `https://chip-beta.publicdataobservatory.org/` from the staging webroot and backend. The port-80 beta host redirects to HTTPS except for ACME challenges. Let's Encrypt certificate expires 2027-02-14T13:13:19+00:00; `certbot.timer` is enabled, the renewal dry run passed, and a successful renewal reloads Nginx. UFW allows 443/tcp. No repository application or live service changed.

**Claude-owned follow-up:** update `docs/PROJECT_HANDBOOK.md`, `infra/staging/README.md`, and the maintained staging Nginx configuration to reflect the public beta host and avoid route drift. The active system configuration is `/etc/nginx/sites-available/chip-beta`; preserve its ACME challenge path, redirect, certificate paths, and staging-only API routes. This Codex branch contains only the diary/status handoff and has not been merged, committed, or pushed.

## Beta access code renewal (2026-11-16)

At John's direction, existing staging access code ID 22 (`Beta staging verification`) was extended by 30 days to 2026-12-22T00:13:50.676282+00:00. The code itself is unchanged and remains active; its restricted local file still matches the staging database hash. Only staging access-code metadata changed. Live access codes were not changed.
