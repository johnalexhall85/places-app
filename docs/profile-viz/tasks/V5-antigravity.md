# Task V5 (Antigravity): independent chart audit and reader guide

Assigned by Claude, 2026-11-19. Work in `/home/john/chip-agy-viz` on branch `agy/profile-viz`. Claude has already merged Codex's endpoints into it. Run Python as `cd backend && PYTHONPATH=. python3 -m pytest ...` (system Python, as in V2). If a module is missing, record that in your status file.

**You own:**
- `backend/tests/test_profile_charts_audit.py`
- `deliverables/profile-viz/**`
- `docs/profile-viz/status/antigravity.md`

Do not commit, deploy, or use sudo. Make no network calls except to `http://127.0.0.1:8003` (a dev backend Claude runs from this branch on `places_staging`). Write no database rows. Record your facts in your status file and stop.

## Read first

1. [PLAN.md](../PLAN.md) and the whole of [CHART_CONTRACT.md](../CHART_CONTRACT.md).
2. `backend/app/community/charts.py`, but only to learn the endpoint paths. **Audit against the contract, not against this code.**
3. `backend/app/area_pilot/lookup.py`: `area_values`, `area_measure_series`, `national_series`, `measure_values_within`.

## Build

1. `backend/tests/test_profile_charts_audit.py` calls the staging HTTP API. It takes the base URL and access cookie from the environment (`CHIP_AUDIT_BASE`, `CHIP_AUDIT_COOKIE`), and skips when they are unset. Claude supplies them.
   - It fetches `/charts` for:
     - 10 counties chosen with a fixed seed from at least 5 states, always including 01063, 01055, and 09003;
     - 5 states, including 01 and 11;
     - 3 districts, including 5401.
   - It checks every rule in contract section 1 for every row:
     - no `places` or `brfss` row has a state or national marker;
     - count measures have no markers;
     - district trends are null;
     - `places` trend style is `dots_ci`;
     - periods in each series ascend;
     - a null value always carries a non-empty `status_text`;
     - `peers.count` is at least the length of `peers.values`, and `min` ≤ every value ≤ `max`;
     - the marker period equals the row period.
   - For 50 rows chosen with a fixed seed, it compares `value`, the uncertainty bounds, and each `trend.series` entry with the same values read directly through the lookup functions. Use a DB session from `app.db.SessionLocal`; it is read-only.
     - Numbers match exactly.
     - National values match `national_series`.
   - It fails when the response for a county is over 400 kB.
2. `deliverables/profile-viz/reading-the-charts.md` is a one-page guide for profile users, in plain language and under 600 words. It explains:
   - the dot and its interval;
   - the state and U.S. markers, and when they are absent;
   - why PLACES county figures are compared only with other counties, and not with the state survey figure;
   - why PLACES years are separate dots with no line;
   - overlapping 5-year ACS windows;
   - that overlapping intervals are not a significance test.

   It must not name a ranking, a "better" or "worse" judgement, or a trend claim.

## Done when

- The audit passes, or each failure is listed in your status file with the GEOID, measure, field, expected value, and actual value.
- The status file has a V5 row and a section headed `## V5 diary facts — <ISO timestamp with timezone>`.

Finish with a report of 10 lines or fewer.
