# Task H2a (Antigravity): CMS Original Medicare GV history parser

Follow [H2-antigravity.md](H2-antigravity.md). Product key `cms_gv`.

- **Registry:** `backend/app/area_pilot/registry/history/cms_gv.json`, which has 5 measures × years 2019–2023 at state and county level.
- **Source role `gv_csv`:** the CMS 2014–2024 Geographic Variation CSV (UTF-8 with BOM). The fixture is `backend/tests/fixtures/history/cms_gv/om_gv_sample.csv`, real rows cut from the archived file: 112 rows, years 2018–2024.

## Rules specific to CMS

- **Header:** it must contain `config['selection']['dimensions']` and every measure's `source_field`.
- **Rows kept:** only `BENE_AGE_LVL == config['selection']['age_level']` (`All`) and `YEAR` equal to a period the registry declares. Ignore other years and age levels, but count them in evidence.
- **Levels:** `BENE_GEO_LVL` `State` → `state` and `County` → `county`. `National` rows are not stored; count them.
- **Exclusions:** apply `config['selection']['exclusions']`. These are the same rules the current adapter applies. The `code_pattern` and `desc_pattern` fields are regular expressions; `code` and `desc` are exact matches.
- **Values:** reuse `app.area_pilot.cms_gv.parse_value(raw, measure, suppression_token)` for the value and status. The history measure needs the current registry's measure fields (`kind`, `storage_scale`, and so on). Take them from `app.area_pilot.cms_gv.load_registry()` by `measure_id`; do not duplicate them.
- **Boundary vintage:** in the fixture, Connecticut 2019–2021 rows use the old county codes `09001`, `09003`, and so on, and 2022–2023 rows use `09110`, `09120`, and so on. The registry already assigns the vintages; check in a test that `09001`/2021 gets vintage `2020` and `09110`/2022 gets `2024`.
- **Parts:** one part per year, named `year_<YYYY>`.
