# Task H2c (Antigravity): CDC BRFSS state history parser

Follow [H2-antigravity.md](H2-antigravity.md). Product key `brfss`.

- **Registry:** `backend/app/area_pilot/registry/history/brfss.json`, which has 20 state measures and 87 measure-years from 2017 to 2022. Each period's `locator` names its own `question_id` and `response_id`; CDC renames variables between years.
- **Source role `brfss_csv`:** a Socrata CSV export of view `dttw-5yxu`, already filtered to `break_out='Overall'` and the 87 selections.
- **Fixture:** `backend/tests/fixtures/history/brfss/brfss_2017_2022.csv`. It is the **complete** real extract (4,786 rows), so the tests can assert the exact totals.

## Rules specific to BRFSS

- **Blank cells:** Socrata CSV writes absent fields as empty strings. Convert `''` to `None` before validating a row, because the current adapter's JSON rows use `None`.
- **Reuse the current helper:** call `app.area_pilot.brfss.parse_observation(row, measure, config)` for each row. Build its arguments like this:
  - `measure` is the current registry measure (`app.area_pilot.brfss.load_registry()`, matched by `measure_id`) with `observation_period`, `question_id`, and `response_id` replaced from the history period.
  - `config` is the current registry config with `expected_locations` replaced by the history registry's `selection.expected_locations`.

  It checks the question text, response, topic, filters, and location, and it raises on any difference. Do not catch that error: a wording change in an older year must stop the parser and be reported.
- **Matching rows:** each row must match exactly one declared (year, question_id, response_id). An unmatched row raises.
- **Dropped locations:** `location_kind` `median` (98, 99) and `source_only` (66 Guam, 78 Virgin Islands) rows are dropped and counted in evidence by year and kind. Every other location becomes a `state` row with its `locationid` as the GEOID.
- **Status and uncertainty:** status comes from `parse_observation`. Uncertainty is `ci95`, with `low`/`high` from `ci_low`/`ci_high`. `source_value` is the raw `data_value` (an empty string when absent).
- **Duplicates:** a repeated (measure, year, location) is an error.
- **Parts:** one part per year, named `year_<YYYY>`.
- **Tests:**
  - The exact total of stored rows, and of dropped median and territory rows.
  - Kentucky (`21`) or Pennsylvania (`42`) for a year in which CDC footnotes it as unavailable, if the fixture has one; otherwise any `not_available` row.
  - One CI check.
  - The 2018 COPD row uses `CHCCOPD1`.
  - A question-text change raises.
