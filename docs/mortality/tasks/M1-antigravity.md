# Task M1 (Antigravity): CDC heart disease and stroke mortality as a shared area product

Assigned by Claude on 2026-11-21.
- Work in `/home/john/chip-agy-mort` on branch `agy/mortality`.
- The migration `c3e7a1f5b9d2_add_mortality_area.py` is already in the branch and applied to `places_staging`.
- The two source CSVs are already archived in `data/ingest/cdc_hds_mortality_2024/` in your worktree.

**You own, for this task only:**
- New files:
  - `backend/app/area_pilot/hds_mortality.py`, `hds_mortality_api.py`, and `hds_mortality_cli.py`
  - `backend/app/area_pilot/registry/cdc_hds_mortality_2022_2024.json`
- Additions only (no rewrites) to:
  - `backend/app/area_pilot/lookup.py`, `router.py`, and `registry/comparability.json`
  - `backend/app/mcp_server/config.py`
  - `frontend/src/main.jsx`, `frontend/src/utils/routeResolver.js`, `frontend/src/pages/Places2025Pilot.jsx`, and its `.test.jsx`
- New tests: `backend/tests/test_area_mortality_hds.py` and `test_area_mortality_hds_postgis.py`.
- `docs/mortality/status/antigravity.md`.

Edit nothing else. If a test outside these paths fails because of your change, report it; don't fix it.

**Rules:**
- Do not commit, push, merge, deploy, or use sudo.
- Make no network calls.
- Write no database rows. Unit tests use small fixtures. The PostGIS test only reads `places_staging` and skips cleanly when no release exists.
- Never edit the project diary, the handbook, `AGENTS.md`, or `alembic/`.
- Write normally formatted source: JSX broken across lines, unminified CSS, and Python lines of about 120 characters or fewer.

## Read first
- [CONTRACT.md](../CONTRACT.md): the shared rules and §1. Measure IDs, labels, status mapping, limitations, and boundaries are fixed there.
- The template is CMS GV, which also has national, state, and county rows. Copy its structure file for file and keep the same function names:
  - `backend/app/area_pilot/cms_gv.py`, `cms_gv_api.py`, `cms_gv_cli.py`, and `registry/cms_om_gv.json`
  - `backend/tests/test_area_cms_gv.py` and `test_area_cms_gv_postgis.py`
- For the Connecticut rule, see `LEGACY_CT_COUNTIES` in `svi.py`.
- `backend/alembic/versions/c3e7a1f5b9d2_add_mortality_area.py`, for the tables `stage_cdc_hds_mortality` and `observation_cdc_hds_mortality`.

## Part A: backend
1. **`hds_mortality.py`:**
   - Parse both CSVs with `utf-8-sig`, keeping only the Overall/Overall rows.
   - Stage every kept row with `source_file` (the file name), `source_level`, `source_code` (the padded `LocationID`), `source_period` `2022–2024`, and the full row as `record`.
   - Match codes exactly to the 2024 boundaries, the way `cms_gv.py` does.
   - Map statuses per the contract. Anything unexpected raises an error.
   - Write `fetch` (download the two URLs and record SHA-256 hashes with `epa_aqi.file_evidence`), but do not run it.
2. **`hds_mortality_cli.py`:** the same subcommands as `cms_gv_cli.py`, with a `--skip-fetch` option so that Claude can stage from the archived files.
   - Validation must check the contract counts: 3,226 counties, 56 states, and 1 nation per file, with 16 and 20 suppressed counties.
   - It must also check the Durham County (37063) and national check values.
3. **`hds_mortality_api.py`:** the same interface as `cms_gv_api.py`, for levels national, state, and county.
   - Use `quantile_breaks` legends, as PLACES does.
   - Add the product status text for `suppressed` from the contract.
4. **`lookup.py`:**
   - Add a `Spec('cdc_hds_mortality', …)` with uncertainty `'none'`, a `MISSING_STATUS` entry returning `not_in_release`, and national reference support, as CMS GV has.
   - Add no `SOURCE_CREDITS` entry.
5. **`router.py`** and **`comparability.json`:** add the branches and an entry beside CMS GV, per the contract's comparability rule.
6. **Tests:** cover the parser (an Overall row, a stratified row that is skipped, a `~` blank row, a bad token, a legacy Connecticut code, the national row) and the API metadata. Run:
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_area_mortality_hds.py tests/test_area_mortality_hds_postgis.py tests/test_area_lookup.py tests/test_area_cms_gv.py -q`

## Part B: map and MCP (only after Part A passes)
7. **Frontend:**
   - Add the route `/area/heart-stroke-mortality`, rendering `<Places2025Pilot dataset="hds_mortality" />`.
   - Add the product wherever CMS GV appears in `Places2025Pilot.jsx`, with the default measure `heart_disease_death_rate`, state→county geography, and the contract's menu label.
   - The explanation must say that these are age-adjusted death rates for adults 35 and older, and that county rates are spatially smoothed.
   - Run `cd frontend && npx vitest run src/pages/Places2025Pilot.test.jsx && npm run build`.
8. **MCP:** add `'cdc_hds_mortality'` to `PUBLIC_PRODUCTS` and the contract §4 sentence to `RULES`. Run `pytest tests/test_mcp_*.py -q`. If a test hard-codes a product count, report it; don't change it.
9. **Profiles must not change.** Run:
   `pytest tests/test_community_api.py tests/test_community_state.py tests/test_community_charts_api.py -q`
   then `git diff --exit-code docs/beta/contract-examples`.

## Report
Update `docs/mortality/status/antigravity.md` with:
- the files changed (`git status --short`)
- every test command and its pass/fail count
- any failures, with the reason
- open questions

Then stop.
