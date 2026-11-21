# Mortality: data contract

Rules for all three products:
- CHIP publishes the source's rates as released. It computes no rates, counts, ranks, trends, or totals, and it does not average or combine measures.
- Areas are matched by exact FIPS code to CHIP's 2024 TIGER boundaries (states and counties), as in `svi.py`. A source code that doesn't match is staged as `source_only` with a reason and is not published.
  - Connecticut appears in all three sources as its eight former counties (`09001`–`09015`). These are staged with the reason `legacy_connecticut_county_code`. The nine planning regions then read `not_in_release`.
  - Do not crosswalk Connecticut or any other code.
- The national row is stored as `geo_level` `national`, `geoid` `US`, `boundary_status` `national_reference`, as in CMS GV.
- **Status:** a number greater than 0 is `available`. A source suppression or insufficient-data marker is `suppressed`, with a NULL value. Any other token stops the run. A zero or negative rate also stops the run.
- **Tables:** `area_pilot.stage_<product>` and `area_pilot.observation_<product>`, from migration `c3e7a1f5b9d2`.
  - The stage primary key is (`release_id`, `source_file`, `source_level`, `source_code`, `source_period`).
  - The observation primary key includes `observation_period`. `value` is `Numeric(12,5)`, and `source_value` keeps the raw text.
- **Legend:** release-wide quintiles, as PLACES uses (`quantile_breaks`). The colour ramp is the shared Blues ramp. A higher value means more deaths.
- **Comparability:** values share an axis only with the same measure from the same product and release. Mortality products never share an axis with each other, or with any other product. State and national markers are allowed for `cdc_hds_mortality` and `nci_cancer_mortality`, and not for `nchs_drug_poisoning`.

## 1. CDC heart disease and stroke mortality (`cdc_hds_mortality`)

**Source files**, archived in `data/ingest/cdc_hds_mortality_2024/`:

| File | data.cdc.gov ID | Rows | SHA-256 |
|---|---|---|---|
| `mri7-5jtw.csv` | `mri7-5jtw` | 78,792 | `fdfac5f8d2550e2a986a3b2c21a0ff8f3ae9f4721f7fb60c1b8aefdc37c885bc` |
| `y5ii-knwc.csv` | `y5ii-knwc` | 78,792 | `71bba020b46efcf07a2ae5195d0eb14711bfbe37da75de0f0c04c8d64787b26e` |

Both were fetched from `https://data.cdc.gov/api/views/<id>/rows.csv?accessType=DOWNLOAD`.

**Dataset ID:** `cdc_hds_mortality_2022_2024`. Map route: `/area/heart-stroke-mortality`. Data-source menu label: "CDC heart disease and stroke deaths".

**Rows used:** only those with `Stratification1 = Overall` and `Stratification2 = Overall`: 3,226 county, 56 state, and 1 nation row per file.
- The `Year` field reads `2023`, the midpoint. The observation period is `2022–2024`.
- `GeographicLevel`, mapped to CHIP levels: `Nation` → national, `State` → state, `County` → county.
- The area code is `LocationID`. Pad it to 2 digits for states and 5 for counties. The nation's `LocationID` is `0`.
- State rows for territories that have no 2024 TIGER state are `source_only` (reason `no_2024_boundary`).

| measure_id | File | Label |
|---|---|---|
| `heart_disease_death_rate` | `mri7-5jtw.csv` | Heart disease death rate, adults 35 and older (per 100,000, age-adjusted) |
| `stroke_death_rate` | `y5ii-knwc.csv` | Stroke death rate, adults 35 and older (per 100,000, age-adjusted) |

- **Value type:** copy the `Data_Value_Type` text. Counties read "Age-adjusted, Spatially Smoothed, 3-year Average Rate"; states and the nation read "Age-adjusted, 3-year Average Rate".
- **Population text:** "Adults aged 35 and older".
- **Status:** a blank `Data_Value` with `Data_Value_Footnote_Symbol` `~` ("Insufficient Data") is `suppressed`. This occurs for 16 heart disease and 20 stroke counties.
- **Product status text:** `suppressed` → "Insufficient data (CDC Heart Disease and Stroke Atlas)".
- **Check value:** Durham County, NC (37063) reads heart disease 227.2 and stroke 71.2. The nation reads 315.3 and 75.9.
- **Uncertainty:** none (`'none'` in `lookup.SPECS`).

**Limitations:**
1. These are CDC's age-adjusted death rates for adults 35 and older, averaged over 2022–2024. They are not the share of people with the disease.
2. County rates are spatially smoothed by CDC, which borrows strength from neighbouring counties. State and national rates are not smoothed.
3. CDC publishes no confidence interval for these rates. Small differences between counties may not be meaningful.
4. Connecticut values are for its former counties and are not shown on the 2024 planning-region boundaries.

## 2. NCI cancer mortality (`nci_cancer_mortality`)

**Source files**, archived in `data/ingest/nci_scp_mortality_2024/`: six CSV exports, `<site>_county.csv` and `<site>_state.csv`. Each was fetched from:

`https://statecancerprofiles.cancer.gov/deathrates/index.php?stateFIPS=00&areatype=<county|state>&cancer=<code>&race=00&sex=0&age=001&year=0&type=death&sortVariableName=rate&sortOrder=default&output=1`

The files are encoded as `latin-1` and have text above and below the table. Each county file has 3,143 counties and a `United States` row (`00000`). Each state file has 53 area rows, including the US row; codes with no 2024 TIGER state are `source_only` (reason `no_2024_boundary`).

| measure_id | Site code | File prefix | Label | Counties suppressed |
|---|---|---|---|---|
| `cancer_death_rate_all` | `001` | `all` | Cancer death rate, all sites (per 100,000, age-adjusted) | 58 |
| `cancer_death_rate_lung` | `047` | `lung` | Lung and bronchus cancer death rate (per 100,000, age-adjusted) | 418 |
| `cancer_death_rate_colorectal` | `020` | `colorectal` | Colon and rectum cancer death rate (per 100,000, age-adjusted) | 943 |

The archive also holds `breast_female_*` and `prostate_*`. These are not published in this package.

**Dataset ID:** `nci_cancer_mortality_2020_2024`. Map route: `/area/cancer-mortality`. Menu label: "NCI cancer deaths".

- **Columns used:** `FIPS`; `Age-Adjusted Death Rate`; `Lower CI (Rate)` and `Upper CI (Rate)`, stored as `ci_low` and `ci_high` (uncertainty `ci95`); and `Average Annual Count`, kept in the stage `record` only.
- **Area codes:** `00000` → national `US`; `SS000` → state `SS`; anything else → county.
- **Observation period:** `2020–2024`, read from the file's title line. If the title line differs, the run stops.
- **Value type:** `age_adjusted_rate`. Population text: "All ages, both sexes (2000 U.S. standard population)".
- **Status:** a rate of `*` is `suppressed`. In these rows the count reads "3 or fewer". Fewer than 16 deaths in the period triggers suppression.
- **Product status text:** `suppressed` → "Suppressed by NCI (fewer than 16 deaths in 2020–2024)".
- **Check value:** Durham County (37063), all sites: 132.6 (127.2–138.2). The US reads 143.2.

**Limitations:**
1. These are NCI's age-adjusted death rates for 2020–2024, with 95% confidence intervals. They are deaths, not new cases.
2. Rates based on few deaths are suppressed by NCI. A suppressed county did not have zero deaths.
3. Connecticut values are for its former counties and are not shown on the 2024 planning-region boundaries.

## 3. NCHS drug poisoning mortality (`nchs_drug_poisoning`)

**Source file:** `data/ingest/nchs_drug_poisoning_county/rpvx-m2md.csv`.
- 59,584 rows, for 2003–2021, with about 3,136 counties per year.
- SHA-256: `822bae06e376f62947e745aa9dfba079d46e641ec8e6906449fa00cbff617b03`.
- The catalog lists it as last updated 2023-04-20.

**Dataset ID:** `nchs_drug_poisoning_2021`. Map route: `/area/drug-poisoning-mortality`. Menu label: "NCHS drug poisoning deaths (modelled)".

**Rows:** only `Year = 2021` is published in this package. Every 2003–2021 row is staged, so that a later history task can use them. `FIPS` is zero-padded to 5 digits.

| measure_id | Column | Label |
|---|---|---|
| `drug_poisoning_death_rate` | `Model-based Death Rate` | Drug poisoning death rate, model-based (per 100,000, age-adjusted) |

- **Uncertainty:** `ci95`, from `Lower Confidence Limit` and `Upper Confidence Limit`. The label reads "95% interval from NCHS's model".
- **Value type:** `model_based_age_adjusted_rate`. Population text: "All ages (2000 U.S. standard population)".
- **Status:** every 2021 value is present. A blank value stops the run.
- **Check value:** Durham County (37063) in 2021 reads 23.87115 (22.12165–25.75957).

**Limitations:**
1. These are NCHS model-based estimates, not counts of recorded deaths. NCHS says that they may over- or under-estimate true rates, and that they may not match CDC WONDER.
2. Drug poisoning means ICD-10 underlying causes X40–X44, X60–X64, X85, and Y10–Y14 (all intents).
3. NCHS has not updated this file since 2023. Its latest year is 2021.
4. Connecticut values are for its former counties and are not shown on the 2024 planning-region boundaries.

## 4. MCP
Add each product to `PUBLIC_PRODUCTS` and add one `RULES` sentence: "Mortality rates are published by the source, age-adjusted; never add them, compare them across mortality products, or call a suppressed value zero." Tool contract Amendment 6 records the change (Claude).

## 5. Profile sections (added 2026-11-21 at John's request)

**Endpoints:** `GET /api/community/county/{geoid}/deaths` and `GET /api/community/state/{geoid}/deaths`, modelled on `/hazards` (`backend/app/community/hazards.py`).
- They read only through `app.area_pilot.lookup.area_values`, and add no ranks, changes, differences, or composites.
- Each row carries the `lookup` value object, with `citation`, `status`, `status_text`, and the uncertainty as returned.
- The existing `/county/{geoid}`, `/state/{geoid}`, `/charts`, `/peers`, and `/hazards` responses do not change. The `docs/beta/contract-examples` snapshots stay byte-identical.
- The existing profile JSON and CSV will list mortality rows automatically once the products are published. The vulnerability Amendment 1 accepted the same for SVI and NRI.

**County response:**
- `heart_stroke`: rows for `heart_disease_death_rate` and `stroke_death_rate`. Each row has `county`, `state`, and `us` value objects, so the page can show the state and national reference values beside the county.
- `cancer`: the three cancer measures, with the same `county`, `state`, and `us` objects.
- `drug_poisoning`: `drug_poisoning_death_rate` for the county only, with no state or U.S. value.
- `sources` and `limitations`.

**State response:** `heart_stroke` and `cancer`, with `state` and `us` objects. There is no `drug_poisoning`, because NCHS publishes no state value in this file.

**Page section:** "Death rates", on the county and state profiles.
- One table per product. The columns are Measure, [County], [State], and United States.
- Each value shows its period and the source's age-adjustment note. For cancer and drug poisoning, the 95% interval appears in smaller text.
- Each product has a one-line note taken from its first limitation. Drug poisoning also states that it is a model-based 2021 estimate.
- Each table links to its `/area/*` map.
- Suppressed values show their `status_text`, never 0 or a blank.
- The profile pages must skip the three mortality products in every other section, as they do for SVI and NRI.
- The CSV and PDF exports follow the existing behaviour.
