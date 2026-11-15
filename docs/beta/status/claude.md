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
| B1 Source specification | In progress | `claude/brfss-b1` | |
| B2 BRFSS product | Not started | | |
| B3 Read layer and contract | Not started | | Codex builds against the contract draft until this lands. |
| B4 Promotion | Waits for John's staging review | | |
