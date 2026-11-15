# Claude status: data and platform track

Read with [the execution plan](../EXECUTION_PLAN.md). Updated at the end of every work package.

| Package | State | Branch | Notes |
|---|---|---|---|
| C0.1 Git base | Done | `claude/beta-phase0` | John pushed `main` (`0195959`) and `beta` (`1e859e6`) on 2026-11-15. The live checkout is on `main`. AHRF branch check: nothing unmerged. |
| C0.2 Repository setup | Done, merged to local `beta` | `claude/beta-phase0` | `apiBase.js` tracked, diary union merge, plan, ownership rules, status files. Alembic now follows `DATABASE_URL`. |
| C0.3 Staging environment | Done | `claude/beta-phase0` | `places_staging` verified identical to live at copy time (revision, 203 tables, 863 indexes, pointers). Service enabled on 8001, Nginx on 8080. Deploy script now builds with `VITE_API_BASE_URL=/api`. |
| C0.4 Coverage matrix | Done | `claude/beta-phase0` | [COVERAGE_MATRIX.md](../COVERAGE_MATRIX.md): C1 and C2 measure lists and showcase counties 37145, 54039, 06019. |
| C0.5 `area_pilot/lookup.py` and data contract | Done | `claude/beta-phase0` | Rechecked on staging. |
| C1 PLACES expansion | Done on staging | `claude/beta-c1-places` | 13 measures at county and tract level. Staging active release `7bf96574-ac68-4d2f-9db8-95b07fbbf622` (parent county `6f265cd8-809b-402d-a7c2-415301f93ba9`). Catalog now has 39 measures. Not on live. |
| C2 ACS expansion | Done on staging | `claude/beta-c2-acs` | New independent product `census_acs5_2024_community_profile`, seven measures at state, county, and tract level. Staging release `d90070e6-0358-499b-b992-4ca6b8b42eb3`. [Guide](../../../backend/docs/chip_acs_community_profile.md). Not on live. |
| C3 Congressional districts | Done on staging | `claude/beta-c2-acs` | Same release carries 437 district estimates; `cd_boundary_119` loaded; `lookup` has district functions. Migration `d5a2f7c9e1b4`. Not on live. |
| C4 Recovery and promotion runbook | Done, merged and deployed to staging | `claude/beta-c4-recovery` | Commit `6993096`. [Recovery guide](../../../backend/docs/chip_beta_c4_recovery_set.md): fresh pre-beta live set, ten pointers, 1,405 source files, isolated restore matched all 66 baseline lines, 37 final checksums passed; temporary test resources removed. [Promotion runbook](../PROMOTION_RUNBOOK.md) remains a Gate 3 draft; promotion requires another fresh set. |
| C5 Handbook and staging browser checks | Documentation and checks done; product defect open | `claude/beta-c5-handbook` | Handbook rewritten for current staging beta; source-map browser findings in the four product guides merged and deployed as `0833d11`. HRSA site detail pointer overlap is assigned to the product track below. |

## Current data contract and product handoff

- Staging `beta` contains C1–C5 data, recovery, and guide commits; inspect `git -C /home/john/chip-beta rev-parse HEAD` for its current commit. The staging database is at Alembic `d5a2f7c9e1b4`. The catalog has **46 measures**, and the three showcase counties (Person NC `37145`, Kanawha WV `54039`, Fresno CA `06019`) have 46 of 46 available. PLACES has seven Person County tracts for each of its 13 measures. Kentucky and Pennsylvania have `not_published` for twelve 2023 PLACES measures.
- New lookup product key `acs_profile` has Census-published total population, poverty, age 65 and over, under 18, disability, uninsured (all ages), and limited English at state, county, tract, and `cd` levels. State benchmarks exist. [Contract and rules](../DATA_CONTRACT.md) and [after-C3 examples](../contract-examples/after-c3/) are current. Suggested district WV-01 `5401` has 28 wholly contained counties, 347 HRSA sites, 56 nursing homes, and 60 TRI facilities; Fresno County overlaps four districts.
- **Product-track requests:** finish X5 district API/page/search and X6 district walkthrough; add the new ACS and PLACES measures to topics and the county profile; keep the two insurance definitions visibly separate; add the ACS community source map with district geography; rerun the Gate 1 source audit against the C1–C3 pointers. No district page is in the current staging build.
- **Staging browser checks:** all 13 PLACES measures and a diabetes tract viewport passed. All five USDA and EPA AQI measures, CT/PR/Alaska exceptions, national/tract messages, county popup, and 390 px layout passed. On `/area/usda-fea` at 1365 × 900, after enabling the HRSA overlay, the site table's “Details” button was covered by sibling panel content. Playwright's ordinary pointer click failed even after scrolling the overlay body; keyboard Enter opened the correct detail. At 390 × 844 the panel had no document overflow and keyboard detail worked, but the button also sat under other content. **Product-track request:** fix the overlay layout in the Codex-owned frontend and repeat normal clicks at both widths before Gate 3. See the product guides.
- A staging-only demo access code exists in the private operator location recorded in the diary. `gh` is not signed in; merges into `beta` are local through `infra/staging/deploy-staging.sh <branch>`. Live remains at ten active pointers and Alembic `c8f1e4a7d3b6`.

## Gate 3 handoff

Rechecked by Claude on 2026-11-15T15:03Z at staging `beta` `4633cad`: every product-track request above is done and deployed (district briefing and search, 46 measures in profiles and topics, ACS community source map, HRSA Details pointer fix, 47-check source audit, full district walkthrough leg). Both tracks have no remaining staging work. Promotion is **not approved or run**: John reviews Gate 3 and approves a specific `beta` commit, then the [promotion runbook](../PROMOTION_RUNBOOK.md) applies, starting with a new live recovery set and exact digest comparison.

## Promotion (2026-11-15)

John approved Gate 3. Claude promoted `f48704e` to live between 15:05Z and 15:32Z following the runbook: fresh recovery set, fast-forward, migration, digest-matched PLACES county, PLACES tract, and ACS community releases, district boundaries, webroot, backend restart. Live has eleven pointers and serves the reviewed bundle. Outstanding: authenticated live walkthrough and PDF check (needs a live access code from John), and pushing `main`.

## BRFSS and state profiles (plan approved 2026-11-15)

Read with [the BRFSS and state plan](../BRFSS_STATE_PLAN.md). The beta packages above are complete and live.

| Package | State | Branch | Notes |
|---|---|---|---|
| B1 Source specification | Done | `claude/brfss-b1` | Twenty measures fixed and verified at CDC; [guide](../../../backend/docs/chip_brfss_state_prevalence.md); registry `brfss_state_2023.json`. |
| B2 BRFSS product | Done on staging | `claude/brfss-b1` | Release `8ca50183-0b61-4302-8e3b-6e06cc8a35dd`, migration `e6b3a8d0f2c5`, 1,082 observations, twelve values checked against CDC. Not on live. |
| B3 Read layer and contract | Done on staging | `claude/brfss-b1` | `lookup` product `brfss`, `state_survey_companions`, `brfss_medians`, `state_counties`, `states`, `paired_measure`. [Contract section](../DATA_CONTRACT.md) and [examples](../contract-examples/after-brfss/). |
| B4 Promotion | Done 2026-11-15 | `claude/brfss-b4-record` | `2d35117` promoted to live; live BRFSS release `5c61bade-38bb-41dd-8728-ce5f4921975f`; twelve pointers; digests matched staging. |

### What Codex can rely on now (BRFSS)

- Staging has twelve pointers and Alembic `e6b3a8d0f2c5`. The catalog has 66 measures. County and district lookups are unchanged (46 values for the showcase counties).
- `area_values(db, 'state', [fips])` returns 33 rows per state. Kentucky (`21`) and Pennsylvania (`42`) return `not_published` for the nineteen 2023 BRFSS measures and a value for dental visits (2022): use Kentucky to test that state.
- `/api/area/*` serves `dataset_id=cdc_brfss_state_prevalence` with `geography=state`; see the contract for the extra `reference` block in `table`.
- Suggested example state: North Carolina `37` (contains Person County). The current walkthrough still passes with the wider catalog.
- **Requests:** follow the labelling rules in the contract's BRFSS section, especially "State survey estimate (BRFSS)" on county cards and "median of states and DC". The seven unpaired BRFSS measures go on state pages only.

## Map consistency package (plan approved 2026-11-15)

Read with [the map consistency plan](../MAP_CONSISTENCY_PLAN.md). **Note for Codex:** by John's instruction Claude is editing `frontend/**` and `backend/app/community/**` on branch `claude/map-consistency` for this package. Please do not start frontend work on the same files until it is merged to `beta`; record any need here or in your status file.

| Package | State | Branch | Notes |
|---|---|---|---|
| M1 One header | Done on staging | `claude/map-consistency` | `SiteHeader` on every page; Log out and gated Funding Model Builder kept; funding methodology on `/methodology`; old pop-ups removed. |
| M2 Brand guide on maps | Done on staging | `claude/map-consistency` | Brand tokens in `index.css`; 229 legacy chrome colours swapped; one Blues ramp for `/area/*` and (beyond the first answer, see diary) the legacy map's sequential scales. |
| M2b Quintile breaks and ramp contrast | Done on staging | `claude/map-consistency` | `quantile_breaks` in the PLACES, ACS income, AHRF, and CLH legends. Open: lopsided fixed breaks for three AQI and three state-level ACS community measures. |
| M3 Area read endpoint | Done on staging | `claude/map-consistency` | `lookup.area_info(..., geometry=True)`; `GET /community/area/{level}/{geoid}`. |
| M4 Tooltip, legend, selection, tools, search on `/area/*` | Done on staging | `claude/map-consistency` | Popups removed. |
| M5 Maps open zoomed to the place | Done on staging | `claude/map-consistency` | `focus=<level>:<geoid>` from county, state, and district profiles; legacy map accepts county and state. |
| M6 Verify, staging, documents | Done | `claude/map-consistency` | Frontend 155 tests, area/community backend 241, `npm run test:beta` all legs on staging `5fb2720`. Not on live. |

| M7 County shapes fit together | Done | `claude/map-consistency` | Added after John's staging review: grid snapping in `backend/app/geometry_sql.py`, zoom-based grid from both map generations, legacy layer redraw fix. |

| M8 Promotion | Done 2026-11-15T23:02Z | `claude/map-consistency` | `e7e8e68` live, application only; same bundle as staging; twelve pointers unchanged. Signed-in check on live is John's. |

### What Codex can rely on now (map consistency)

- Import the header from `components/SiteHeader` (or the old `components/Header` path); do not add page-specific headers. `components/PlaceSearch` takes `onSelect` for in-page use.
- Map links from any page can add `&focus=<level>:<geoid>`; `mapFocus(level, geoid)` in `CommunityPages.jsx` builds it.
- Colours for any new map come from `branding/mapColors.js`; tooltips from `utils/mapTooltip.js`.
- The source audit under `deliverables/` was **not** rerun: no pointer or value changed. Screenshots there predate the new header and ramps and need refreshing by Codex if John wants them current.
- Shape queries must use `fitted_geom()` from `app/geometry_sql.py`; pages pass `gridForZoom(zoom)` as `simplify`.

## Legacy map retirement (2026-11-15, John's request)

| Package | State | Branch | Notes |
|---|---|---|---|
| L1 Retire legacy map | Done; live | `claude/retire-legacy-map` | `App.jsx` and its private modules deleted; `/explore/map` opens the area map; Data source menu has nine published maps. Done by Claude in Codex-owned `frontend/**` at John's direction. |

- **For Codex:** do not link to the legacy map or import from `App.jsx`; it no longer exists. Link maps to `/area/*` (or `/explore/map`, which opens PLACES).

## Map polish (requested by John 2026-11-15)

| Package | State | Branch | Notes |
|---|---|---|---|
| P1 Map loading animations and motion | Done on staging; not live | `claude/map-polish` | John confirmed Claude edits Codex-owned `frontend/**` for this change. New [MapLoading](../../../frontend/src/components/MapLoading.jsx) component (animated SVG observatory mark, first-load overlay, loading pill, legend skeleton) and motion CSS in `Places2025Pilot.css`. |

- **For Codex:** `ObservatoryMark` and `LegendSkeleton` in `frontend/src/components/MapLoading.jsx` are reusable for other loading states; the community pages still show plain "Loading …" text.
