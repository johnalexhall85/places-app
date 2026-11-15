# ACS 2020–2024 community characteristics and congressional districts

**Status, 2026-11-15:** published on **staging only** as release `d90070e6-0358-499b-b992-4ca6b8b42eb3`. Not on live. Built for the funder beta (work packages C2 and C3).

## What it is

An independent shared area product, `census_acs5_2024_community_profile`, with its own registry ([acs_2024_profile.json](../app/area_pilot/registry/acs_2024_profile.json)), tables, and release pointer. The published median-income product (`census_acs5_2024_b19013`) is separate and unchanged.

| Measure ID | Census variable | Universe |
|---|---|---|
| `total_population` | `S0101_C01_001` | Total population |
| `poverty_pct` | `S1701_C03_001` | Population for whom poverty status is determined |
| `age_65_plus_pct` | `S0101_C02_030` | Total population |
| `age_under_18_pct` | `S0101_C02_022` | Total population |
| `disability_pct` | `S1810_C03_001` | Civilian noninstitutionalized population |
| `uninsured_pct` | `S2701_C05_001` | Civilian noninstitutionalized population |
| `limited_english_pct` | `S1601_C06_001` | Population 5 years and over |

All seven come from the ACS 5-year **subject tables** (`https://api.census.gov/data/2024/acs/acs5/subject`), so each percentage and its 90% margin of error is the Census Bureau's own figure. CHIP computes nothing. Total population uses the subject-table variable rather than `B01003` so that one endpoint serves every measure.

Levels: state (52, including DC and Puerto Rico), county (3,222), tract (85,382), and **congressional district of the 119th Congress** (437: 435 districts plus the DC and Puerto Rico delegates). District values are the Census Bureau's district tabulations (summary level 500). They are never built from counties or tracts.

## Source facts verified on 2026-11-15

- Variable labels and concepts are pinned in the registry (`source_variables`, checksum `source_variables_sha256`); retrieval fails if any changes.
- `geography.json` lists summary levels 040, 050, 140, and 500 with reference date 2024-01-01, and district names read "Congressional District N (119th Congress)".
- The district request returns 440 rows. Three are "Congressional Districts not defined" (code `ZZ`; Connecticut, Illinois, New Hampshire) with zero residents. They are excluded and listed in the candidate report; any other set of excluded states fails validation.
- Census codes: estimate `-666666666` with annotation `-` (too few sample observations), `-999999999`/`N`, `-888888888`/`(X)`; margin `-222222222`/`**`, `-333333333`/`***`, `-555555555`/`*****` (controlled estimate, no sampling margin). Percent sentinels arrive as `-666666666.0`. A code without its matching annotation, an unknown negative value, a percentage above 100, or a missing margin without a code is rejected.
- District boundaries are TIGER/Line 2024, one archive per state (`TIGER2024/CD/tl_2024_{state}_cd119.zip`); there is no national file. `ZZ` shapes are not loaded.

## Tables (migration `d5a2f7c9e1b4`, additive)

- `area_pilot.cd_boundary_119`: 437 district shapes, EPSG:4326, with the archive checksum per row.
- `area_pilot.stage_acs_profile`: one original API row per area.
- `area_pilot.observation_acs_profile`: one row per area and measure, with `value`, `moe`, both annotations, and `status` (`available`, `true_zero`, `missing`, `suppressed`, `not_applicable`). Published rows are immutable (trigger).

## Commands

From `backend/`, with `DATABASE_URL` pointing at the intended database:

```bash
.venv/bin/python -m app.area_pilot.acs_profile_cli load-cd-boundaries      # once; idempotent, verifies stored shapes
.venv/bin/python -m app.area_pilot.acs_profile_cli fetch-stage-validate   # about 160 API requests, a few minutes
.venv/bin/python -m app.area_pilot.acs_profile_cli review CANDIDATE_UUID
.venv/bin/python -m app.area_pilot.acs_profile_cli approve-publish CANDIDATE_UUID \
  --semantic-sha256 … --schema-sha256 … --metadata-sha256 …
.venv/bin/python -m app.area_pilot.acs_profile_cli rollback RELEASE_UUID
.venv/bin/python -m app.area_pilot.acs_profile_cli deactivate
```

A Census API key is required (`CENSUS_API_KEY` or the key file used by the income product). Original response bytes are archived under `data/ingest/acs5_2024_profile/<run>/` with SHA-256 provenance; district archives are under `data/ingest/acs5_2024_profile/cd_boundaries/`. `review` rechecks every archived file, the staged content digest, and every observation against its staged source row. Identical content records a duplicate run. A changed same-label source is held. The product is not on the weekly timer.

## Staging release

- Candidate `d90070e6-0358-499b-b992-4ca6b8b42eb3`: 11 of 11 checks; 89,093 areas; 623,651 observations.
- Digests: semantic `227317d9ceea9365a82781da0b8eac8a957177b3456c46a129dfb990c7953443`, schema `b0c8a7f77257d684030da13f911f10291fc6dd073febcf44468fa825005c56e0`, metadata `897472a52b8dc52f80f63f455038fe2ca5552a93021eda44f6a575987d1fe41c`.
- Status counts: tract 582,627 available, 9,452 zero, 5,595 missing; county 22,476 available, 78 zero; state 364; district 3,059.
- Independent check: 13 values each for Kanawha County, WV-01, West Virginia, and tract `54039000100` equal a separate Census API request.
- Drill: `deactivate`, a refused rollback to a PLACES release ID, `rollback` to the release; a direct `UPDATE` of a published row was rejected by the trigger.

Promotion to live reruns these commands on live and requires the same three digests.

## Read API and interpretation

Shared API `/api/area/{catalog,map,legend,table}` with `dataset_id=census_acs5_2024_community_profile` and `geography` of `state`, `county`, `tract`, or `cd`. Single-place reads go through `app.area_pilot.lookup` (product key `acs_profile`), which also provides `district_counties`, `county_districts`, `state_districts`, and facilities inside a district.

- Each percentage has its own universe; they are not shares of the same group.
- Tract margins are often large. Show the margin with every value.
- State and county population totals are controlled to official estimates and have no sampling margin. That is shown as such, not as zero uncertainty.
- The ACS uninsured share (all ages, survey) is not comparable with the PLACES insurance measure (modeled, adults 18–64).
- County–district overlap shares are area shares from the boundaries. They are not population shares, and county values shown with a district are context only.
- No frontend map page exists for this product yet; that is product-track work.
