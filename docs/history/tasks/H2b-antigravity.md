# Task H2b (Antigravity): USDA Food Environment Atlas history parser

Follow [H2-antigravity.md](H2-antigravity.md). Product key `usda_fea`.

- **Registry:** `backend/app/area_pilot/registry/history/usda_fea.json`. It has 5 county measures with one earlier variable each: `PCT_LACCESS_LOWI15`, `SNAPSPTH17`, `WICSPTH16`, `FMRKTPTH13`, `PCT_LACCESS_HHNV15`.
- **Source roles:**
  - `values_csv`: long format `FIPS,State,County,Variable_Code,Value`, UTF-8 with BOM.
  - `variables_csv`: `VariableList.csv`.
- **Fixtures:**
  - `backend/tests/fixtures/history/usda_fea/StateAndCountyData_sample.csv`: 112 real rows, including current-year codes and two unrelated codes, which must be ignored.
  - `backend/tests/fixtures/history/usda_fea/VariableList.csv`: the full file.

## Rules specific to USDA

- **Headers:** the values header must equal `config['selection']['expected_values_header']`. Each locator's `variable_code` must appear in `VariableList.csv` with exactly the locator's `variable_name`; otherwise raise.
- **Selection:** keep only rows whose `Variable_Code` is a declared locator. Pad FIPS to 5 digits only if the source omits the leading zero, and count how often that happens in evidence. A FIPS ending in `000` is a state or national row: count it and drop it.
- **Values:** reuse `app.area_pilot.usda_fea.classify_value(raw, measure, config)`. Take the measure's `plausible_range` and `kind` from the current registry (`app.area_pilot.usda_fea.load_registry()`) by `measure_id`, and pass a config with the history `sentinels`. Statuses are `available`, `true_zero` (value 0), `not_available` (`-9999`, `N/A`, blank), and `did_not_exist` (`-8888`). `classify_value` already returns `true_zero` for a zero; use its status unchanged.
- **Duplicates:** a repeated (FIPS, variable) is an error.
- **Parts:** one part per period, named `period_<YYYY>`.
- **Tests:** the fixture has Valdez-Cordova `02261` and Shannon/Oglala Lakota `46113`/`46102`. Emit them as published. The store decides boundary matching, not the parser.
