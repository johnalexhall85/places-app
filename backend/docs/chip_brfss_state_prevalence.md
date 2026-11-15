# CDC BRFSS state prevalence (shared product)

**Status, 2026-11-15:** published on **live** as release `5c61bade-38bb-41dd-8728-ce5f4921975f` and on staging as `8ca50183-0b61-4302-8e3b-6e06cc8a35dd`; both reproduce the digests below. Additive migration `e6b3a8d0f2c5` (`stage_brfss`, `observation_brfss`).

## Source

CDC's [BRFSS Prevalence Data (2011 to present)](https://data.cdc.gov/Behavioral-Risk-Factors/Behavioral-Risk-Factor-Surveillance-System-BRFSS-P/dttw-5yxu) on data.cdc.gov (Socrata `dttw-5yxu`, public domain). CHIP reads the **Overall** breakout, **crude prevalence**, one response per measure, for 2023 and (dental visits only) 2022, so the years match the BRFSS years behind PLACES 2025. The registry is [brfss_state_2023.json](../app/area_pilot/registry/brfss_state_2023.json).

The dataset has no release number and is revised whenever CDC adds a year. A CHIP release is identified by its content digest; the Socrata revision timestamps are stored as provenance (`source_before`) and are deliberately not part of the metadata digest.

## Measures

Twenty measures. Thirteen pair with the PLACES measures CHIP shows (`places_measure_id` in the registry); a pair has the same year and population. Seven are state-only.

| Measure | BRFSS question ID | Response published | Year | Pairs with PLACES |
|---|---|---|---|---|
| Diagnosed diabetes | `DIABETE4` | Yes (pregnancy-related and pre-diabetes are separate responses) | 2023 | `diabetes_crudeprev` |
| High blood pressure | `_RFHYPE6` | Yes | 2023 | `bphigh_crudeprev` |
| Obesity | `_BMI5CAT` | Obese (BMI 30.0 - 99.8) | 2023 | `obesity_crudeprev` |
| Coronary heart disease | `CVDCRHD4` | Yes | 2023 | `chd_crudeprev` |
| Stroke | `CVDSTRK3` | Yes | 2023 | `stroke_crudeprev` |
| COPD | `CHCCOPD3` | Yes | 2023 | `copd_crudeprev` |
| Current asthma | `_CASTHM1` | Yes | 2023 | `casthma_crudeprev` |
| Depression | `ADDEPEV3` | Yes | 2023 | `depression_crudeprev` |
| Frequent mental distress | `_MENT14D` | 14+ days when mental health not good | 2023 | `mhlth_crudeprev` |
| Current cigarette smoking | `_RFSMOK3` | Yes | 2023 | `csmoking_crudeprev` |
| Routine checkup within the past year | `CHECKUP1` | Within the past year | 2023 | `checkup_crudeprev` |
| Current lack of health insurance, 18–64 | `_HCVU653` | Do not have some form of health insurance | 2023 | `access2_crudeprev` |
| Dental visit in the past year | `_DENVST3` | Yes | 2022 | `dental_crudeprev` |
| Binge drinking | `_RFBING6` | Yes | 2023 | — |
| No leisure-time physical activity | `_TOTINDA` | No | 2023 | — |
| Fair or poor self-rated health | `_RFHLTH` | Fair or Poor Health | 2023 | — |
| Frequent physical distress | `_PHYS14D` | 14+ days when physical health not good | 2023 | — |
| Arthritis | `_DRDXAR2` | Yes | 2023 | — |
| Kidney disease | `CHCKDNY2` | Yes | 2023 | — |
| Could not see a doctor because of cost | `MEDCOST1` | Yes | 2023 | — |

## Coverage and statuses

- 2023: 54 CDC locations (48 states, DC, Guam, Puerto Rico, Virgin Islands, two median rows). **Kentucky and Pennsylvania have no 2023 rows** in the CDC file (verified: zero rows of any kind). They are read as `not_published`. 2022: 56 locations, including both.
- 1,082 observations (19 × 54 + 56), all with a published value in this release.
- `location_kind`: `state` (joins a CHIP state boundary: 50 states, DC, Puerto Rico), `source_only` (Guam `66`, Virgin Islands `78`; stored, not mapped), `median` (`98` All States and DC, `99` All States, DC and Territories). Median rows carry CDC footnote `**`, have no confidence limits, and their sample-size column holds the number of jurisdictions.
- `not_available` is reserved for a row CDC publishes without a value under footnote `*` (fewer than 50 respondents in the denominator, relative standard error above 30%, or data not collected). None occurs in the current selection.
- `sample_size` is the number of respondents who gave the published response.

## Interpretation

- A BRFSS state figure is a direct survey estimate. A PLACES county or tract figure is modeled from the same survey. Shown together, the state figure is context, not a ranking benchmark.
- Crude prevalence, not age-adjusted.
- The median rows are medians of jurisdictions, not national estimates.
- No state value is derived from counties, and responses are not combined.

## Operator commands

From `backend/` of a checkout whose `DATABASE_URL` selects the intended database:

```bash
python -m app.area_pilot.brfss_cli fetch-stage-validate
python -m app.area_pilot.brfss_cli review <candidate>
python -m app.area_pilot.brfss_cli approve-publish <candidate> --semantic-sha256 … --schema-sha256 … --metadata-sha256 …
python -m app.area_pilot.brfss_cli rollback <published release>
python -m app.area_pilot.brfss_cli deactivate
```

Validation checks: `source_stable`, `schema_matches_registry`, `exact_keyset` (every measure × its year's reviewed location list, nothing more), `medians_present`, `boundary_join`, `documented_missing_states`. Every source row is also checked against the registry's question text, response text, topic, breakout, value type, unit, and location code before staging; any difference holds the candidate. A same-label content change is held for review.

Archives are under `data/ingest/brfss_state_2023/<run>/` (five files per run).

## Staging publication record, 2026-11-15

| Item | Value |
|---|---|
| Release | `8ca50183-0b61-4302-8e3b-6e06cc8a35dd` |
| Semantic | `5dcbd5bdfef6ae4d35d02992a37f85f6f2de8684d6d1a0c4e412c58f0908951d` |
| Schema | `9904968919efd340425d72e7d28d61ecec94a4af038d7fc19e147e6f9a45905e` |
| Metadata | `05839404d17d7fa755012d888b0a63112075995616f20dbbe9208654d3de389d` |
| Socrata revision at retrieval | `rowsUpdatedAt` 1789482408 |

Verified: twelve stored values (ten states and territories, one median, across twelve measures) equal separate per-location CDC API queries, including confidence limits and response counts; published rows reject updates; deactivate and rollback restore the pointer; a repeat run is reported as a duplicate; the other eleven staging pointers are unchanged. Map, legend, and table endpoints return 52 state shapes with Kentucky and Pennsylvania as `not_published` for 2023.

## Read API and lookup

See the BRFSS section of the [data contract](../../docs/beta/DATA_CONTRACT.md).
