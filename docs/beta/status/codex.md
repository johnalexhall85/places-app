# Codex status: product track

Read with [the execution plan](../EXECUTION_PLAN.md). Codex updates this file at the end of every work package.

| Package | State | Branch | Notes |
|---|---|---|---|
| X1 Community API | Done; merged and deployed to staging | `codex/beta-x1-community-api` | Staging `beta` at `6f76e0d`; authenticated Nginx reads passed for catalog, search, county profile, comparison, facilities, topics, tract route, and CSV. Local focused tests: 13 passed. Full suite: 655 passed, two unrelated source-dependent failures with ignored inputs absent; the known FY2026 source mismatch remains when inputs are linked. |
| X2 Landing, navigation, county profile, brand tokens | Done; merged and deployed to staging | `codex/beta-x2-landing-profile` | Staging `beta` was at `8cd7412` after X2. Root landing, `/explore/map` legacy route, county profile, brand tokens. Frontend 144/144 tests and Vite build passed; authenticated desktop/mobile browser walkthrough passed with 28 Person County cards, seven topic tiles, no page errors or horizontal overflow. X4 later connected topic cards to topic pages. |
| X3 Comparison and PDF export | Done; merged and deployed to staging | `codex/beta-x3-comparison-pdf` | Three-showcase comparison renders 28 aligned indicators through authenticated Nginx, with no page errors or document overflow at 390 px. PDF endpoint reuses Playwright profile rendering with the current demo session cookie; 200 response, 9-page PDF, source and income text verified. Backend 656 tests passed with two unrelated source-dependent cases deselected; frontend 146/146 and build passed. |
| X4 Topics and tract patterns | Done; merged and deployed to staging | `codex/beta-x4-topics-tracts` | Seven API-driven topic pages and source-map measure preselection; profile displays ACS published tract shapes and an explicit PLACES empty state until a combined release is active. Frontend 147/147 and build passed. Authenticated desktop/mobile browser checks passed. |
| X5 District briefing | Done; merged and deployed to staging | `codex/beta-x5-district-briefing` | WV-01 API and page show seven Census district estimates, mapped facilities, and 28 named overlapping counties; state/district picker and ACS community source map support 119th Congress geography. C1/C2 measures are in topics and county profiles; the two insurance definitions are explicitly distinct. HRSA Details pointer clicks passed at 1365 and 390 px after panel layout correction. Staging `beta` at `631a8ca` for code, with documentation follow-up pending. |
| X6 End-to-end tests and polish | Core walkthrough and polish deployed; district leg pending C3 | `codex/beta-x6-walkthrough-polish` | About and methodology routes, shareable map views, five staging review images, and repeatable authenticated Playwright walkthrough. Frontend 148/148 and build passed. Gate 1 source audit checked 30 values across seven products against release-linked archived files, profile, and PDF. District walkthrough and C1/C2 content refresh remain. |

## What Claude can rely on now

- The X1 API is available through staging Nginx. A staging-only access code is stored outside the repository at `/home/john/.local/share/chip/staging-beta-access-code` (mode 600); ask John to retrieve it on the VM for review. The seven topic definitions are initial product copy; C1 and C2 measures must be added when published.
- X4 topic routes and within-county tract view are on staging `beta`; ACS Person County shows seven source-published tracts from the profile's active release. The PLACES tract view correctly reports no rows under the current county-only active release.
- Gate 1 is ready for John to review on staging: landing/search, three showcase profiles, comparison, PDFs, topic pages, legacy area and funding routes, and 30 archived-source checks passed. Evidence and screenshots are under `deliverables/beta/`. No live promotion was made.

## Blocked or waiting

- C1 has published the combined PLACES county/tract release on staging. X6 must recheck Person County's 13 PLACES tract measures in the profile and walkthrough.
- Claude added `VITE_API_BASE_URL=/api` to the staging deploy script; X5 deployed with the durable setting.
- PDF rendering needs `PROFILE_FRONTEND_BASE_URL=http://127.0.0.1:8080` in staging `backend/.env`; Codex set it locally (mode 600). Promotion needs a live-appropriate value. Gate 1 archived-source and legacy-route checks passed on current staging releases; John has not yet reviewed the gate.
- X6 still needs the district leg and full post-C1/C2/C3 walkthrough, refreshed screenshots, and a source audit tied to the current release IDs. The existing Gate 1 report refers to earlier PLACES and predates the ACS community product; it is stale for Gate 3.
