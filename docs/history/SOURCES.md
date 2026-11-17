# Historical periods: source specification (H0)

Checked by Claude on 2026-11-17 between 17:30Z and 18:10Z, against the archived source files and the publishers' live endpoints. The rule is the current period plus up to **five earlier periods** per measure, where the publisher still offers them. The period is always the **observation (data) year or ACS 5-year window**, never the release label. If two releases publish the same data year, keep the one from the newest release and name that release in the note.

| Product (current dataset_id) | Earlier periods | Source | Boundary vintage | Notes |
|---|---|---|---|---|
| CMS OM GV (`cms_om_geographic_variation`) | 2019, 2020, 2021, 2022, 2023 | The 2014–2024 CSV already archived (`data/ingest/cms_om_gv/cfdc7a01-…/om_gv_puf.csv`): same filters, `BENE_AGE_LVL='All'`, other `YEAR` | State 2024; county **2020** for 2019–2021 (CMS rows use the eight old CT counties `09001`…`09015`), 2024 for 2022–2023 | About 3,194–3,197 county rows a year. The CMS national row gives the reference for that year. |
| USDA FEA (`usda_ers_food_environment_atlas`) | One earlier period per measure: `PCT_LACCESS_LOWI15` (2015), `SNAPSPTH17` (2017), `WICSPTH16` (2016), `FMRKTPTH13` (2013), `PCT_LACCESS_HHNV15` (2015) | The same July 2025 `StateAndCountyData.csv` | County **2020** (old CT counties) | USDA publishes nothing older in this release. `-9999` and `-8888` keep their current meanings. |
| AHRF (`hrsa_ahrf_county_2024_2025`) | 2022 (`*_22` in the current file); 2021…2018 from older AHRF releases | Current CSV; `AHRF_2021-2022.ZIP` and older (ASCII fixed-width with a layout file, or SAS) on `data.hrsa.gov/data/download` | County 2020 before 2022, 2024 from 2022 | **Excluded from the MCP server**, as now. The 2022-2023 and 2023-2024 releases are not listed, so data year 2021 is unavailable. 2017–2020 come from the 2021-2022 fixed-width release (field codes such as `f14675YY`), only where its label matches the current technical documentation; the old primary-care label adds "Excl Hsp Res & 75+ Yrs", which must be checked. |
| BRFSS state (`cdc_brfss_state_prevalence`) | 2018–2022 (dental 2018 and 2020 only; it is asked every other year) | The same Socrata view `dttw-5yxu`, `year=<Y>` with the same question/response/`Overall` filters | State | CDC renames variables between years (e.g. COPD `CHCCOPD1`→`2`→`3`); each period's locator names its own ID, and the question text and response must equal the current ones. Blood pressure is 2017/2019/2021; distress measures start in 2019; uninsured and cost barrier in 2021. 87 measure-years. Do not fall back to another year. |
| EPA AQI (`epa_airdata_aqi_county_2025`) | 2020, 2021, 2022, 2023, 2024 | `https://aqs.epa.gov/aqsweb/airdata/annual_aqi_by_county_<Y>.zip` (200 for 2019–2024) | County **2020 for every year** (EPA AQS still reports Connecticut's eight former counties, so they draw for all earlier years) | `no_reported_value` is computed at read time against that year's boundaries, as now. Unreviewed name variants stop the parser. |
| PLACES county + tract (`cdc_places_county_2025_pilot`) | Data years 2018–2022 (BPHIGH and dental are biennial, so fewer). Depression is absent from the 2020 release | Long-format Socrata views. County: `fu4u-a9bh` (2024 release), `h3ej-a9ec` (2023), `duw2-7jbt` (2022), `pqpp-u99h` (2021), `dv4u-3x3q` (2020). Tract: `ai6z-tcin`, `em5e-5hvn`, `nw2y-v4gm`, `373s-ayzu`, `4ai3-zynv`. `datavaluetypeid='CrdPrv'` | County 2020 (CT old counties until the 2024 release; check each release); tract 2010 for releases that use 2010 tracts (the 2020 and 2021 releases), otherwise 2020 | One value per (measure, data year), from the newest release that publishes it. Each is a separate model run, so the note says so. |
| ACS B19013 (`census_acs5_2024_b19013`) | 2015–2019, 2016–2020, 2017–2021, 2018–2022, 2019–2023 | `api.census.gov/data/<Y>/acs/acs5` (200 for 2019–2023) | State; county 2020 before vintage 2022, 2024 after; tract **2010** for 2015–2019, 2020 after | Dollars are in each vintage's own year, so they are **not inflation-adjusted to a common year**; the note says so. 5-year windows overlap. |
| ACS community (`census_acs5_2024_community_profile`) | Same five windows | `…/acs5/subject` (200 for 2019–2023) | Same as B19013 | **No district (`cd`) history:** older vintages use different Congresses' districts. Check each subject-table variable's label for every vintage; a renamed or missing variable is unavailable for that year. |
| AHRQ CLH (`ahrq_clh_2023_curated`) | 2018, 2019, 2020, 2021, 2022 | `https://www.ahrq.gov/sites/default/files/wysiwyg/sdoh/clh_<Y>_{county,tract}_2_0.xlsx`. AHRQ returns 403 without the adapter's browser user agent; with it, 2022 county returned 200 (15 MB) | County 2020 before 2022, 2024 after; tract 2010 for 2018–2019, 2020 after | Check that each year's codebook defines the five variables the same way. |

## Boundaries to add

- `county_boundary_2020`: Census cartographic boundary file `cb_2020_us_county_500k`. It includes the old Connecticut counties.
- `tract_boundary_2010`: Census `cb_2019_us_tract_500k` or TIGER 2010 tracts. Pick one and record it.

Every period row carries its `boundary_vintage`. Rows with a value but no matching shape are kept in the history release. The legend reports their count as `published_without_boundary`, and lookup/MCP reads return them by GEOID. The store's `boundary_match` check holds a candidate when the count exceeds the registry tolerance.

## Not in scope

- District (`cd`) history.
- Inflation adjustment.
- Rebasing old values to new boundaries.
- Trends computed by CHIP: the trend tool returns published values side by side and computes no change score.
- Profiles.
