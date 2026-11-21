# Antigravity status: mortality

## M1 (2026-11-21T01:49Z)

Implemented `cdc_hds_mortality` (CDC Interactive Atlas of Heart Disease and Stroke mortality, 2022–2024) across backend ingest/CLI/API/lookup/router/comparability, `/area/heart-stroke-mortality` map page, and public MCP config. No commits, pushes, merges, deploys, network calls, or database writes were made.

### Files changed (`git status --short`)

```text
 M backend/app/area_pilot/lookup.py
 M backend/app/area_pilot/registry/comparability.json
 M backend/app/area_pilot/router.py
 M backend/app/mcp_server/config.py
 M docs/mortality/status/antigravity.md
 M frontend/src/main.jsx
 M frontend/src/pages/Places2025Pilot.jsx
 M frontend/src/pages/Places2025Pilot.test.jsx
 M frontend/src/utils/routeResolver.js
?? backend/app/area_pilot/hds_mortality.py
?? backend/app/area_pilot/hds_mortality_api.py
?? backend/app/area_pilot/hds_mortality_cli.py
?? backend/app/area_pilot/registry/cdc_hds_mortality_2022_2024.json
?? backend/tests/test_area_mortality_hds.py
?? backend/tests/test_area_mortality_hds_postgis.py
?? frontend/node_modules
```

*(Note: `frontend/node_modules` is a pre-existing symlink to `/home/john/chip-claude/frontend/node_modules`.)*

### Test commands and results

1. **Part A backend tests:**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_area_mortality_hds.py tests/test_area_mortality_hds_postgis.py tests/test_area_lookup.py tests/test_area_cms_gv.py -q`
   - **Result:** `1 failed, 45 passed, 1 skipped`
     - `tests/test_area_mortality_hds.py`: 12 passed
     - `tests/test_area_mortality_hds_postgis.py`: 1 skipped (no active published `cdc_hds_mortality_2022_2024` release in `places_staging` yet)
     - `tests/test_area_cms_gv.py`: 20 passed
     - `tests/test_area_lookup.py`: 13 passed, 1 failed (see Failures below)

2. **Read-only dry-run against archived CSVs (`data/ingest/cdc_hds_mortality_2024/`):**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -c "..."` calling `hds_mortality.retrieve(cfg, skip_fetch=True)` and `hds_mortality_cli.validate_counts_and_checks(stats, cfg)`
   - **Result:** Passed — 6,566 kept rows (3,283 per file: 3,226 counties, 56 states, 1 nation), exact SHA-256 match on both `mri7-5jtw.csv` and `y5ii-knwc.csv`, suppressed county counts verified (16 and 20), and Durham County (`37063`: `227.2` / `71.2`) and national (`315.3` / `75.9`) check values verified.

3. **Frontend tests and production build:**
   `cd frontend && npx vitest run src/pages/Places2025Pilot.test.jsx && npm run build`
   - **Result:** `43 passed (43)` in `src/pages/Places2025Pilot.test.jsx`; `vite build` succeeded cleanly (`dist/index.html`, `dist/assets/index-*.js`, `dist/assets/index-*.css`).

4. **MCP tests:**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv-mcp/bin/python -m pytest tests/test_mcp_*.py -q`
   - **Result:** `2 failed, 26 passed` (see Failures below)

5. **Community profile regression tests and snapshot diff:**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_community_api.py tests/test_community_state.py tests/test_community_charts_api.py -q`
   - **Result:** `15 passed`
   `git diff --exit-code docs/beta/contract-examples`
   - **Result:** Exit code `0` (byte-identical)

### Failures (outside owned files; not modified)

1. `backend/tests/test_area_lookup.py::test_level_filter_returns_only_products_published_at_that_level`
   - **Reason:** Hard-codes the pre-mortality set of state-level products (`assert state == {'acs', 'acs_profile', 'brfss', 'cms_gv', 'fema_nri'}`), which now includes `'cdc_hds_mortality'`.
2. `backend/tests/test_mcp_integration.py::test_search_context_and_sources`
   - **Reason:** Hard-codes `assert len(sources.data['products']) == 10`; with `'cdc_hds_mortality'` added to `PUBLIC_PRODUCTS`, `list_data_sources()` now returns `11` products.
3. `backend/tests/test_mcp_integration.py::test_http_client`
   - **Reason:** `FileNotFoundError: '.venv-mcp/bin/uvicorn'`. The test launches `.venv-mcp/bin/uvicorn` relative to the worktree's `backend/` directory, whereas `.venv-mcp` lives in `/home/john/chip-claude/backend/.venv-mcp` (not present in `/home/john/chip-agy-mort/backend`).

### Open questions / notes for Claude

- **Per-level `value_type`:** Because CDC publishes county rows with `Data_Value_Type = "Age-adjusted, Spatially Smoothed, 3-year Average Rate"` and state/national rows with `"Age-adjusted, 3-year Average Rate"`, the registry stores `value_type_by_level` alongside `value_type`, and `lookup.py` (`area_values`, `measure_values_within`), `hds_mortality_api.py` (`selection`, `metadata`, `national_reference`), and `Places2025Pilot.jsx` (`dataSelection`) resolve `value_type` per level so both county and state queries match stored rows accurately and national reference always resolves when viewing counties.
- **Quintile breaks on `geo_level`:** `legend_breaks.quantile_breaks(..., by_level=True)` filters on column `level`, whereas `observation_cdc_hds_mortality` uses `geo_level` (and shares `value_type` between `state` and `national`). `hds_mortality_api.quantile_breaks` therefore runs the identical `percentile_cont(ARRAY[0.2,0.4,0.6,0.8])` query with `AND geo_level=:level` and returns `legend_breaks.BASIS`, keeping `legend_breaks.py` untouched and ensuring the national row is never included in state quintiles.
- **Suppressed state row:** Note that Connecticut's state-level row (`09`) in both CDC CSVs is also `~` (`Insufficient Data`), in addition to the 16 heart disease and 20 stroke suppressed counties. Both are staged and published with `status='suppressed'` and `value=NULL`.
- **Legacy Alaska county (`02261`):** Both CDC CSVs include `02261` (Valdez-Cordova, suppressed), which is staged as `source_only` (`no_2024_boundary`) alongside the 4 non-2024-TIGER territory states (`60`, `66`, `69`, `78`), 6 territory counties, and 8 legacy Connecticut counties (`09001`–`09015`, reason `legacy_connecticut_county_code`).
