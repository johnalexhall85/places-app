# CHIP funder beta: execution plan

## Context

CHIP today is a set of well-validated federal data maps: ten published shared releases (seven area products with 24 measures, three facility overlays), legacy layers, and the CDC funding pages. A visitor has to know which dataset holds the answer. The product direction document asks for the opposite: pick a place or a question first, and get a cited community profile, a comparison, and a briefing.

The goal of this plan is a beta that a funder such as the Robert Wood Johnson Foundation can open and understand without a guided explanation, in about 4–6 weeks, built by two agents working at the same time on separate tracks.

Decisions already made with John:

| Question | Decision |
|---|---|
| Timeline | About 4–6 weeks |
| Scope beyond the core | Tract patterns in the profile, more measures (PLACES and ACS), congressional district briefings. Mortality is out of this beta. |
| Autonomy | Agents build, migrate, publish, and deploy on a **staging** copy. John reviews at three gates and approves promotion to the live demo. |
| Home page | A new landing page replaces the legacy map as home. The legacy map and per-dataset pages stay reachable under "Explore data". |
| Hosting | Stays HTTP with the access code. John demos by screen share. |
| Showcase places | Agents choose three counties and one district where every dataset has published values. |
| Districts | Congressional only (119th Congress). |
| Git | Fast-forward `main` to the deployed stack first, then work through a shared `beta` branch. |

What I found in the repository that shapes the plan:

- The shared API (`backend/app/area_pilot/router.py`) only answers viewport (bounding box) requests. Nothing returns "all published values for one county". The profile needs that.
- Shared PLACES has only two measures (dental visits, uninsured). Chronic disease is the first topic, so this must widen.
- Shared ACS has one measure (median household income). The adapter (`area_pilot/acs.py`) is built around table B19013.
- A legacy profile already exists at `/profile/county/{fips}` with PDF export (`services/profile_bundle.py`, `profile_pdf_playwright.py`, `pages/ProfileReport.jsx`). It reads the legacy, unpinned tables (older PLACES, ACS 2017–2021, SVI, HPSA). The PDF machinery is reusable; the data path is not the one to build on.
- The live backend runs from `/home/john/places-app` itself (`infra/systemd/places-backend.service`). Agents must not develop in that directory.
- `frontend/src/config/apiBase.js` is git-ignored, so a new worktree cannot build the frontend until that is fixed.
- `codex/ahrf-county-five-measures` is not an ancestor of `main`. Phase 0 checks whether anything on it is still unmerged before anyone relies on it.

## Who does what

The split is by ownership of directories, so the two agents never edit the same file.

| | Claude Code (data and platform track) | Codex (product track) |
|---|---|---|
| Owns | `backend/app/area_pilot/**`, `backend/alembic/**`, `infra/**`, `backend/docs/**`, `docs/PROJECT_HANDBOOK.md`, `docs/beta/**` | `backend/app/community/**` (new), `frontend/**`, `backend/tests/test_community_*`, `deliverables/**` |
| Builds | Staging environment, coverage matrix, single-place read module, PLACES and ACS measure expansion, congressional district data, recovery set, promotion runbook | Community API, landing page, county profile, comparison, topics, exports, district briefing page, end-to-end tests, demo polish |
| Never touches | `frontend/**`, `backend/app/community/**` | `area_pilot/**`, migrations, `infra/**`, the handbook |

Why this way round: the product track is the larger, continuous build, and the ChatGPT Pro allowance for Codex is the larger of the two. The data track is a series of independent work packages that can stop and resume cleanly when a Claude Pro usage window runs out. This is my planning assumption about the two plans; if John upgrades Claude, nothing in the split changes.

Shared rules for both agents:

- **Only Claude creates migrations.** The product track needs none: saved views are URL state, and exports are files.
- **Both write diary entries.** `docs/PROJECT_DIARY.md` gets a `merge=union` rule in `.gitattributes` so two agents adding entries does not conflict. Codex puts handbook-worthy facts in its diary entry; Claude folds them into the handbook.
- **Status files.** Each agent keeps `docs/beta/status/<agent>.md`: work package, state, branch, what the other agent can now rely on. Each reads the other's file at the start of every work package.
- **Merging.** Each agent runs its checks, then runs `infra/staging/deploy-staging.sh <branch>` from its worktree, which takes a lock, merges the branch into `beta` in `/home/john/chip-beta` without force, and deploys staging. (Correction 2026-11-14: `gh` is not signed in on the VM, so these are local merges, not GitHub pull requests. "Merged pull request" elsewhere in this plan means this.) Neither merges to `main`.
- **Database.** Every worktree's `backend/.env` sets `DATABASE_URL` to `places_staging`; the app, area CLIs, and Alembic follow it. Do not run legacy importers outside `app/area_pilot` from a worktree. See `infra/staging/README.md`.
- **Live is off limits** until Gate 3: no writes to the live database, `/var/www/places`, `places-backend`, or the `/home/john/places-app` checkout.
- **When blocked** on the other agent, on a permission, or on a source that will not download: record it in the status file and move to the next work package. Do not wait.

## Workspace layout (set up in Phase 0)

| Path | Branch | Purpose |
|---|---|---|
| `/home/john/places-app` | `main` | Live checkout. Frozen until promotion. |
| `/home/john/chip-beta` | `beta` | Staging backend runs from here. Changes only by merge. |
| `/home/john/chip-claude` | `claude/beta-*` | Claude's worktree |
| `/home/john/chip-codex` | `codex/beta-*` | Codex's worktree |
| `/home/john/places-app-ahrf-push` | existing | Left alone |

Staging environment, all on this VM (289 GB free):

- Database `places_staging` in the existing PostGIS container, restored from a fresh dump of the live database.
- `places-backend-staging.service` on `127.0.0.1:8001`, with its own `.env` and its own demo-access secrets.
- Nginx server on port 8080 serving `/var/www/places-staging`. The community router uses the FastAPI prefix `/community` and is reached at `/api/community/*` through the general `/api/` block, which strips `/api` (the same way `/api/area/*` reaches `/area/*`); no Nginx change is needed. Port 8080 stays closed in the firewall; John views it through an SSH tunnel.
- Agent development backends on 8002 (Codex) and 8003 (Claude), both pointed at `places_staging`.

## Product design

Routes Codex builds (existing routes keep working):

| Route | What it shows |
|---|---|
| `/` | Landing: one sentence on what CHIP is, a place search, seven topic tiles, three showcase examples. |
| `/community/county/{fips}` | County profile |
| `/compare?counties=…` | Up to four counties side by side |
| `/topics`, `/topics/{slug}` | Topic views |
| `/district/cd/{geoid}` | Congressional district briefing |
| `/explore/map` | The legacy map that is home today |

**County profile.** Sections follow the direction document: who lives here; health conditions and prevention; access to care (workforce, health centers, nursing homes); community conditions; food; environment; Medicare use and spending; public-health funding; what this data cannot tell you. Every indicator shows value, unit, period, the population it describes, source and release, published uncertainty where one exists, and the source's own status text when there is no value. A state value appears only where the source publishes one (ACS, CMS). Facility sections give counts and lists from the three published overlays. Tract-capable measures get a small within-county tract map with a link to the full map. SVI, FEMA NRI, and HPSA from the legacy tables appear in a separate "Additional context" section labelled with their vintage. Funding links to the state funding profile and is labelled state-level.

**Comparison.** An aligned table of the same indicators. No ranking, no best/worst colouring, no composite score.

**Topics.** Seven topics from the direction document, defined in `backend/app/community/topics.json` (Codex's file). Each lists its measures, opens the matching map preselected, names the relevant overlays, and states its limits.

**Exports.** PDF briefing, reusing `services/profile_pdf_playwright.py` against a print layout of the profile page; CSV of the indicator table with citation columns; "Copy link" for any profile, comparison, or map view. Word export is a stretch item after Gate 2.

**District briefing.** ACS district estimates labelled as district-level; facilities located inside the district; counties that intersect it, with links to their profiles, labelled as context and never presented as district estimates.

## Visual identity: PDO Brand & Style Guide v1.0 (April 2026)

Every new page and export follows the guide John supplied. A copy is already in the repository at `branding/legacy-chip/backend-assets-brand/PDO_Brand_Style_Guide.pdf`, next to the Word report, fact sheet, and PowerPoint templates. The fonts are already loaded (`frontend/index.html`, `frontend/src/index.css`), but the colour tokens in `frontend/src/branding/pdoBrand.js` (`#3576BA`, `#123247`, and others) do not match the guide and are replaced in X2.

| Element | Rule from the guide |
|---|---|
| Colours | Deep Navy `#003F61` dominant (headers, backgrounds); Brand Blue `#0277BD` for buttons, links, accents; Logo Blue `#3D75C9`; white. Secondary: Data Peach `#F0B97D`, Teal `#009688`, Forest Green `#558B2F`, Steel Grey `#CFD8DC`, at most two per layout. UI: Light Background `#F4F7FB`, Body Text `#1A2F3F`, Muted Text `#546E7A`, Sky Blue `#9FC5E8` (on navy, large text only). |
| Type | Roboto Slab Bold for page titles and big stat numbers only; Arial for everything else. Section headings Arial Bold in Deep Navy, sub-headings Arial Bold in Brand Blue. Body left-aligned, 55–80 characters per line. No third typeface. |
| Spacing | Multiples of 8 px. |
| Charts | Series order `#0277BD`, `#F0B97D`, `#009688`, `#558B2F`, `#3D75C9`, `#003F61`, `#9FC5E8`, `#CFD8DC`. Flat 2D, value-axis gridlines only, axis labels, never colour alone, legible in greyscale. A source line under every chart. |
| Maps | Blues sequential scale, light for lower values to Deep Navy for highest, on the new profile and briefing maps. |
| Logo | PDO icon with the all-caps wordmark, at least 40 px, clear space kept, no recolouring or effects. |
| Voice | Precise, sourced, non-partisan: state the number, period, and source; no alarm words or advocacy. Landing and About copy for funders says specifically what CHIP provides. |
| Exports | PDF briefing follows the Fact Sheet layout (navy header, stat cards beside narrative, footer). The stretch Word export starts from `PDO_Report_Template.docx`. |

Two points where the guide and the existing application meet:

- **Existing map legends are not recoloured.** The published products use fixed display classes with distinct colours for suppressed, missing, and zero values, covered by tests. New maps use the Blues scale for values and keep neutral, labelled non-blue styles for those statuses.
- **Source line format.** The guide's "Source: Agency · Document · Fiscal Year" becomes "Source: Agency · Product · Period · Release" for health data, since most of it is not fiscal-year data.

Codex adds one token file (CSS variables from the table above) used by all new pages, and a contrast check (4.5:1 body, 3:1 large text) to the X6 walkthrough.

## Work packages

### Phase 0 — Foundation (Claude, serial, before Codex starts)

- **C0.1** Check `codex/ahrf-county-five-measures` against `main` and report differences. Fast-forward `main` to `0195959` and push. Create `beta` and the worktrees.
- **C0.2** Stop ignoring `frontend/src/config/apiBase.js`; add the diary union-merge rule; commit this plan as `docs/beta/EXECUTION_PLAN.md`; add a short "beta ownership" section to `AGENTS.md`.
- **C0.3** Build the staging environment and `infra/staging/deploy-staging.sh`. Verify anonymous 401 and an authenticated session on port 8080.
- **C0.4** Coverage matrix, `docs/beta/COVERAGE_MATRIX.md`: user questions × existing measures × missing measures × geography, generated from the registries and the staging database. It fixes the final PLACES and ACS measure lists for C1 and C2 and picks the showcase counties.
- **C0.5** Single-place read module `backend/app/area_pilot/lookup.py`: given a geography and GEOIDs, return each published measure's value, status, uncertainty, period, population, release, and source, plus facility lists for a county. It reads active releases only and never aggregates. Codex calls it and does not query observation tables itself. Its return shape is written into `docs/beta/DATA_CONTRACT.md` with one real JSON example.

Codex starts when C0.5 is merged to `beta`.

### Claude track

- **C1 PLACES expansion.** Extend `registry/places_county_2025.json` and `places_tract_2025.json` from 2 to about 12 measures (candidates: diabetes, high blood pressure, obesity, smoking, COPD, coronary heart disease, stroke, asthma, depression, frequent mental distress, routine checkup). Confirm each measure's data year in the 2025 release. Fetch, validate, review, and publish on staging.
- **C2 ACS expansion.** Generalize the ACS adapter beyond B19013. Add population, poverty, age 65 and over, under 18, disability, uninsured, and limited English, taken from tables where the Census Bureau publishes the percentage and its margin of error, at state, county, and tract level.
- **C3 Congressional districts.** New product: 119th Congress TIGER boundaries with an explicit vintage and ACS 5-year district estimates for the C2 measures (confirm the 2020–2024 release uses 119th boundaries). Read-time relations in `lookup.py`: facilities inside a district; counties intersecting a district.
- **C4 Recovery and promotion.** Fresh recovery set covering all current releases (handbook priority 1). Promotion runbook `docs/beta/PROMOTION_RUNBOOK.md`: back up, migrate live, rerun each ingest on live and require the same content digests that were reviewed on staging, deploy the webroot and Nginx change, verify, and roll back if needed.
- **C5 Handbook** rewritten for the beta, with the pending authenticated browser checks closed on staging.

Each of C1–C3 follows the established product pattern (registry JSON, adapter, CLI, additive migration, unit and PostGIS lifecycle tests, operator guide) and extends `lookup.py`.

### Codex track

- **X1 Community API** in `backend/app/community/`: search, county profile, comparison, topics, facilities, and CSV, all assembled from `lookup.py`, with tests.
- **X2 Landing, navigation, and county profile page.** Replace the tokens in `branding/pdoBrand.js` with the brand guide palette and add the shared CSS token file. Move the legacy map to `/explore/map` in `main.jsx` and `routeResolver.js` without refactoring `App.jsx`.
- **X3 Comparison page and PDF export.**
- **X4 Topics pages**, and the profile's tract-pattern maps (reusing the map code in `pages/Places2025Pilot.jsx`).
- **X5 District briefing page and API** (after C3 lands; until then build against the contract example).
- **X6 End-to-end and polish.** Playwright walkthrough on staging: landing → search → profile → compare → PDF → topic → district. Keyboard access, mobile layout, loading and empty states, About and Methodology copy, refreshed screenshots for `deliverables/`.

As C1–C3 publish new measures, Codex adds them to `topics.json` and the profile sections; no other change is needed.

## Schedule and gates

| Week | Claude | Codex | Gate for John |
|---|---|---|---|
| 1 | Phase 0, start C1 | X1, start X2 | |
| 2 | C1, start C2 | X2, X3 | **Gate 1:** on staging, find a county, read its profile, compare three counties, download the PDF |
| 3 | C2 | X4 | |
| 4 | C3 | X4, X5 | **Gate 2:** expanded measures, topics, tract patterns |
| 5 | C3, C4 | X5, X6 | |
| 6 | C5, promotion | X6 | **Gate 3:** full walkthrough, then John approves promotion to live |

Agents do not stop between gates. A gate is a notice in the status file plus a one-page "what to look at" list; work continues on the next package while John reviews.

## Interpretation rules both agents must keep

- No overall health score and no ranking of communities.
- No county or state value computed from child areas. No district value derived from counties.
- Each indicator keeps its own population, period, and source. Medicare measures are labelled as Original Medicare beneficiaries, never residents.
- Suppressed, missing, not published, and zero stay distinct, as do PLACES 95% intervals, ACS 90% margins, and "no uncertainty published".
- Facilities and conditions shown together are context, not cause. TRI stays "reporting facilities".
- Every number on a page or in an export carries its source, period, and release.
- No secrets in the repository or documents. No force push. No archive deletion. No change to funding methodology.

## What John needs to do

1. Approve this plan.
2. Start each agent in its worktree with its kickoff prompt (below), and restart it with the same prompt after a usage limit; the status file tells it where to resume.
3. If an agent is blocked from creating a staging access code, create one and tell both agents where it is stored outside the repository.
4. Review at Gates 1, 2, and 3.
5. Before showing funders: settle the AHRF redistribution terms (open in the handbook). Until then AHRF stays behind the access code.

Kickoff prompt for Claude Code, run in `/home/john/places-app` for Phase 0 and in `/home/john/chip-claude` afterwards:

> Read `docs/beta/EXECUTION_PLAN.md`, `AGENTS.md`, and both files in `docs/beta/status/`. You are the data and platform track. Carry out the next unfinished Claude work package through to a merged pull request into `beta` and a verified staging deploy, update your status file and the diary, then continue with the next package. Do not touch live systems or Codex-owned paths. Stop only at Gate 3 or if every remaining package is blocked.

Kickoff prompt for Codex, run in `/home/john/chip-codex`:

> Read `docs/beta/EXECUTION_PLAN.md`, `AGENTS.md`, `docs/beta/DATA_CONTRACT.md`, and both files in `docs/beta/status/`. You are the product track. Carry out the next unfinished Codex work package through to a merged pull request into `beta` and a verified staging deploy, update your status file and the diary, then continue with the next package. Read published data only through `app.area_pilot.lookup`. Do not touch live systems or Claude-owned paths, and do not create migrations. Stop only at Gate 3 or if every remaining package is blocked.

## Verification

Per work package:

- Backend: `cd backend && .venv/bin/pytest` (focused tests for the change, then the full suite; one known unrelated failure, `test_all_six_real_source_years_match_acceptance_totals`).
- Frontend: `cd frontend && npm test && npm run build`.
- Data packages: the product's validation checks, `review`, staged publish, a pointer drill (deactivate and rollback), and confirmation that all other active pointers are unchanged.
- Staging: anonymous requests return 401 on port 8080; an authenticated browser session passes the Playwright walkthrough.

At each gate:

- The walkthrough passes on staging for all three showcase counties (and the district at Gate 3).
- Ten indicator values per showcase county, chosen across products, are checked from the profile page and the PDF back to the archived source file.
- Regression: all existing `/area/*` pages, overlays, legacy map at `/explore/map`, and funding pages still load.

At promotion:

- Content digests on live equal those reviewed on staging; live pointers for untouched products are unchanged; the walkthrough passes through live Nginx; the rollback pair (previous webroot and code commit) is recorded in the diary.

## Risks

- **Claude Pro usage limits** will pause the data track several times a week. The work packages are sized to resume from the status file. If C3 slips, the district briefing is the item that moves past week 6; the core beta does not depend on it.
- **ACS district vintage** and the PLACES measure years are unverified until C0.4, C1, and C3 check them at the source.
- **Staging access code:** an earlier session was blocked from minting a demo code. Staging has its own secrets, but John may need to create the code once.
- **Legacy data in the profile** (SVI, FEMA, HPSA) is unpinned and older. It is shown separately and labelled, not mixed with the released indicators.
