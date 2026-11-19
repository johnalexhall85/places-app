# Task V2 (Antigravity): CMS national rows for earlier years

Assigned by Claude, 2026-11-19. Work in `/home/john/chip-agy-viz` on branch `agy/profile-viz`, which is already checked out. Run Python as `cd backend && PYTHONPATH=. .venv-mcp/bin/python ...`. If that venv is missing, use `/home/john/chip-agy/backend/.venv-mcp/bin/python`.

**You own:**
- `backend/app/area_pilot/history/parsers/cms_gv.py`;
- `backend/tests/test_history_parsers_cms_gv*`, including new fixtures under `backend/tests/fixtures/history/cms_gv/`;
- `docs/profile-viz/status/antigravity.md`.

Do not commit, deploy, or use sudo. Make no network calls and write no database rows. Record your facts in the status file and stop.

## Read first

1. [docs/profile-viz/PLAN.md](../PLAN.md) and section 3 of [CHART_CONTRACT.md](../CHART_CONTRACT.md).
2. `backend/app/area_pilot/history/parsers/cms_gv.py`. Today `parse()` counts the `BENE_GEO_LVL == 'National'` rows and skips them (around line 136).
3. `backend/app/area_pilot/cms_gv.py`, mainly `parse_value` and `range_problems`, and how the current CMS release stores the national row (`geo_level='national'`, `geoid='US'`).
4. `backend/tests/test_history_parsers_cms_gv.py` and its fixture `om_gv_sample.csv`.

## Build

1. Add `parse_national(config, files, evidence) -> list[dict]` to `cms_gv.py`. **Leave `parse()` exactly as it is.** Its parts and digests must not change.
2. `parse_national` reads the same `gv_csv` file and applies the same checks `parse()` makes, so a reader can't tell the two apart:
   - the header and dimension checks;
   - age level `All`;
   - only the years declared in the history registry;
   - only the measures and periods declared there.
3. It returns one dict for each National row and declared measure, sorted by (period, measure_id):
   `{'measure_id', 'period', 'level': 'national', 'geoid': 'US', 'value': Decimal | None, 'status', 'source_value'}`.
   - Use the same value parsing and status rules that `parse()` uses for state rows, through `parse_value` and the registry's statuses.
   - `readmission_rate` keeps the CMS 0–1 scale, the same as the state rows.
4. Make `parse_national` add `evidence['national_emitted'] = {year: count}`.
5. It raises `ValueError` if a declared year has no National row, or has more than one.

## Tests

Add them in `backend/tests/test_history_parsers_cms_gv_national.py`:
- Two runs over the fixture give identical output.
- Each declared year has exactly 5 rows (one per measure).
- Values for one year match the fixture text exactly.
- A suppressed or blank national value keeps its status and its value is `None`, not 0.
- A missing National row for a declared year raises `ValueError`.
- A duplicated National row for a declared year raises `ValueError`.
- The existing `parse()` part digests are unchanged. The existing test file still passes untouched.

If the fixture lacks a National row for every declared year, add one per year to a **new** fixture file. Do not edit `om_gv_sample.csv`.

Command: `PYTHONPATH=. .venv-mcp/bin/python -m pytest -q tests/test_history_parsers_cms_gv*.py`

## Done when

The tests pass, and `docs/profile-viz/status/antigravity.md` has two things:
- a V2 row in its table;
- a section headed `## V2 diary facts — <ISO timestamp with timezone>` with three bullets: objective and outcome, files and verification, and what Claude should do next.

Finish with a report of 10 lines or fewer.
