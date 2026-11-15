# CHIP: BRFSS state data, state maps, and state profiles

## Context

The funder beta is live with county profiles, comparison, topics, district briefings, and 46 measures. County profiles show CDC PLACES estimates (modeled from BRFSS) with no state figure beside them, because PLACES publishes none. There is no state profile at all: a state appears only as a benchmark line on Census and Medicare cards and as a funding page.

John wants three things:

1. BRFSS statewide results beside the PLACES measures on county profiles.
2. State-level maps of that BRFSS data.
3. State profiles similar to county profiles, built from measures that are published for states.

Decisions made with John:

| Question | Decision |
|---|---|
| BRFSS years | Match PLACES: 2023, and 2022 for dental visits |
| BRFSS measures | The 13 PLACES measures CHIP shows, plus about seven state-only ones |
| State profile content | Only what CHIP already publishes for states, plus BRFSS. No new state files from HRSA or USDA. |
| Workflow | Same two-agent split, staging first, one review, then live |

## What I verified at the source (read-only, 2026-11-15)

CDC's "BRFSS Prevalence Data (2011 to present)" on data.cdc.gov (Socrata dataset `dttw-5yxu`) publishes crude prevalence with 95% confidence limits and sample sizes by state.

- 2023 "Overall" rows cover 54 locations; 2022 covers 56. Kentucky and Pennsylvania are expected to be the missing 2023 states, as in PLACES. Confirm in B1.
- Every one of the 13 PLACES measures has a matching BRFSS question in 2023:

| CHIP PLACES measure | BRFSS question ID | Response to publish |
|---|---|---|
| Diabetes | `DIABETE4` | Yes |
| High blood pressure | `_RFHYPE6` | Yes |
| Obesity | `_BMI5CAT` | Obese |
| Coronary heart disease | `CVDCRHD4` | Yes |
| Stroke | `CVDSTRK3` | Yes |
| COPD | `CHCCOPD3` | Yes |
| Current asthma | `_CASTHM1` | Yes |
| Depression | `ADDEPEV3` | Yes |
| Frequent mental distress | `_MENT14D` | 14+ days |
| Current smoking | `_RFSMOK3` | Yes |
| Routine checkup | `CHECKUP1` | Within the past year |
| Uninsured, 18–64 | `_HCVU653` | No coverage |
| Dental visit (2022) | confirm ID in the 2022 rows | Yes |

- Proposed state-only additions, all present in 2023: binge drinking (`_RFBING6`), no leisure-time physical activity (`_TOTINDA`), fair or poor health (`_RFHLTH`), frequent physical distress (`_PHYS14D`), arthritis (`_DRDXAR2`), kidney disease (`CHCKDNY2`), could not afford to see a doctor (`MEDCOST1`). B1 fixes the final list and exact response labels.

Not yet verified: exact response strings, the dental question ID for 2022, footnote and suppression codes, and how the national "median of states" rows are coded.

## Design

**One new independent data product**, `cdc_brfss_state_prevalence`, in the shared pipeline: its own registry, release, and pointer, state level only. It follows the PLACES pattern, which already handles a Socrata source with no formal release number (`backend/app/area_pilot/source.py`: revision metadata, keyset paging, stability check, measure-set digest).

**Interpretation rules (in addition to the existing ones):**

- A BRFSS state figure is a direct survey estimate; a PLACES county figure is a model built from that survey. On a county card it is labelled "State survey estimate (BRFSS)" with its own year, confidence interval, and source line. It is context, not a benchmark the county is ranked against.
- A state BRFSS value is never derived from PLACES counties, and no state value anywhere is a sum or average of counties.
- Insurance now has three separate measures: Census (all ages, survey), PLACES (18–64, modeled), BRFSS (18–64, state survey). They stay visibly separate.
- Kentucky and Pennsylvania show "not published" for 2023 measures. Suppressed, missing, and not published stay distinct.
- The "all states and DC" row in BRFSS is a median of states, not a national estimate. If shown, it is labelled exactly that.
- Crude prevalence only, to match the PLACES crude prevalence CHIP shows.

**State profile** at `/community/state/{fips}`, same layout and PDF/CSV exports as the county profile:

| Section | Content | Source |
|---|---|---|
| Who lives here | Income and the seven community measures | Census ACS (already published for states) |
| Health conditions, prevention and access | About 20 BRFSS measures | new BRFSS release |
| Medicare use and spending | Five measures | CMS (already published for states) |
| Mapped facility locations | Counts of health center sites, nursing homes, TRI reporting facilities | existing overlays (`lookup.area_facilities` already supports state) |
| Places in this state | Links to county profiles and congressional districts | `lookup.state_districts`, new `state_counties` |
| Funding | Link to the existing state funding profile | existing |
| What this data cannot tell you | Workforce, food, air quality, and community conditions are published for counties only and are not summed to the state | |

**State map** at `/area/brfss`: state choropleth for each BRFSS measure with table, statuses, and confidence intervals, built on the existing source-map page (`frontend/src/pages/Places2025Pilot.jsx`), state geography only.

## Who does what

Ownership is unchanged (see `AGENTS.md`): Claude owns `backend/app/area_pilot/**`, migrations, `infra/**`, `backend/docs/**`, the handbook, `docs/beta/**`. Codex owns `backend/app/community/**`, `frontend/**`, `deliverables/**`, its status file. Codex reads data only through `app.area_pilot.lookup`. Only Claude creates migrations.

### Claude track

- **B1 Source specification.** Confirm at the source: question IDs, response labels, years, the 54 and 56 location lists, footnote codes, national rows, and the final list of extra measures. Write `backend/docs/chip_brfss_state_prevalence.md` and the registry `backend/app/area_pilot/registry/brfss_state_2023.json` (each measure: BRFSS question ID, response, year, population, and `places_measure_id` where a PLACES measure matches).
- **B2 BRFSS product.** Adapter, CLI (`fetch-stage-validate`, `review`, `approve-publish`, `rollback`, `deactivate`), map API under `/api/area`, and one additive migration (stage and observation tables). Reuse `source.py` for Socrata access and digests, the state shapes in `area_pilot.acs_boundary_2024`, and the immutability trigger. Validation checks: exact keyset, expected state count per year, documented missing states, boundary join, source stability, sample parity with the API. Territories without a CHIP boundary are recorded as source-only. Unit tests and a guide. Publish on staging; pointer drill; confirm the other eleven pointers are unchanged.
- **B3 Read layer.** In `backend/app/area_pilot/lookup.py`: a `brfss` spec at state level; `source_credit` stays `null`; a documented pairing so a caller can ask for the BRFSS state value that corresponds to a PLACES measure (`places_measure_id` from the registry, exposed in the catalog); `state_counties(db, state_geoid)`; state names for search. Update `docs/beta/DATA_CONTRACT.md` with real examples under `docs/beta/contract-examples/after-brfss/`. Existing examples stay untouched.
- **B4 Promotion.** Extend `docs/beta/PROMOTION_RUNBOOK.md` with a BRFSS section (digests reviewed on staging, order, rollback). After John's review: fresh recovery set, fast-forward, migration, digest-matched ingest on live, deploy, verify. Update handbook and diary.

Codex can start on Y1 against the contract as soon as B3 is merged to `beta`; until then it builds against the planned shape in the contract draft.

### Codex track

- **Y1 Community API.** In `backend/app/community/`: state profile, state search (extend the existing search so a state name finds the state), state CSV and PDF, and the BRFSS companion value on county profile rows. Tests.
- **Y2 State profile page** `/community/state/{fips}` with the sections above, reusing the county profile components in `frontend/src/community/CommunityPages.jsx`, the print styles, and the brand tokens. Route in `main.jsx` and `routeResolver.js`.
- **Y3 County profile and comparison.** Show "State survey estimate (BRFSS)" on each PLACES card and in the PDF and CSV. Add a link from a county profile to its state profile. The comparison page is unchanged apart from carrying the new line where it shows state values.
- **Y4 BRFSS state map** at `/area/brfss`, added to the data-source selector, with measure preselection from topics. Add BRFSS measures to `topics.json` and link topic pages to the state map.
- **Y5 Landing, walkthrough, evidence.** Landing search accepts states and shows one example state. Extend `frontend/scripts/beta-walkthrough.mjs` with a state leg (profile, PDF, map). Extend the source audit in `deliverables/beta/` with BRFSS samples for three states. Refresh screenshots.

## Sequence and review

| Step | Claude | Codex |
|---|---|---|
| 1 | B1, B2 | Y1 and Y2 against the contract draft |
| 2 | B3, staging publish | Y3, Y4 |
| 3 | B4 runbook section | Y5 |
| Review | John reviews on staging: a county profile with state BRFSS lines, a state profile and its PDF, the state map | |
| 4 | Promotion to live after John's approval | |

Agents do not stop between steps. Each merges into `beta` and deploys with `infra/staging/deploy-staging.sh <branch>`, updates its status file in `docs/beta/status/`, and adds a diary entry. Live is untouched until John approves.

## What John needs to do

1. Approve this plan.
2. Start Codex in `/home/john/chip-codex` with the prompt below; restart it with the same prompt after a usage limit.
3. Review on staging when both status files say ready.
4. Approve promotion.

Kickoff prompt for Codex:

> Read `docs/beta/BRFSS_STATE_PLAN.md`, `AGENTS.md`, `docs/beta/DATA_CONTRACT.md`, and both files in `docs/beta/status/`. You are the product track only. Merge `beta` into your branch first. Carry out the next unfinished Y package through to a merge into `beta` and a verified staging deploy, update `docs/beta/status/codex.md` and the diary, then continue with the next package. Read published data only through `app.area_pilot.lookup`. Do not touch live systems or Claude-owned paths, and do not create migrations. Do not do Claude-track packages even if they are unfinished; record what you are waiting for and continue with other Y work. Stop when all Y packages are deployed on staging.

Claude's first action after approval is to commit this plan as `docs/beta/BRFSS_STATE_PLAN.md` and reset both status files for the new packages.

## Verification

- **Data (B2):** all validation checks pass; ten sampled values across states and measures match the CDC API; Kentucky and Pennsylvania are `not_published` for 2023; pointer drill (deactivate, rollback) works; eleven existing pointers unchanged; published rows immutable.
- **Tests:** `cd backend && .venv/bin/python -m pytest tests/test_area_*.py tests/test_community_*.py`; `cd frontend && npm test && npm run build`.
- **Staging:** `npm run test:beta` passes including the new state leg; the source audit passes with BRFSS samples; anonymous requests return 401.
- **By eye on staging:** Person County profile shows a labelled BRFSS state line on each PLACES card; North Carolina's state profile and PDF read correctly; a Kentucky profile shows "not published" for 2023 measures; the state map renders every measure.
- **Promotion:** live candidate digests equal those reviewed on staging; live and staging `lookup` output match for three states and three counties; rollback pair recorded.

## Risks and open points

- **Definitions may not line up exactly.** A PLACES measure and its BRFSS question can differ in detail (for example, how the diabetes question treats pregnancy-related diabetes). B1 records each pairing and its wording; a pairing that does not hold is shown on the state profile only and not on county cards.
- **The Socrata dataset has no release number** and CDC can revise it. The release is identified by its revision metadata and content digest, as PLACES is.
- **HRSA workforce data** stays out of state profiles, consistent with the pending redistribution question.
- **Claude usage limits** may pause B2 or B4; packages resume from the status file.
- **Not in this plan:** a state comparison page, BRFSS 2024, age-adjusted prevalence, and breakdowns by age, sex, or race.
