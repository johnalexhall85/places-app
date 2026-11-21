# Antigravity status: mortality

## M3 (2026-11-21T02:17Z)

Implemented `nchs_drug_poisoning` (NCHS Drug Poisoning Mortality by County, model-based; staging all 2003–2021 rows and publishing 2021 county-level rates with 95% intervals from NCHS's model) across backend ingest/CLI/API/lookup/router/comparability, `/area/drug-poisoning-mortality` map page, and public MCP config. Reused helpers by import from `hds_mortality`, `hds_mortality_cli`, and `hds_mortality_api`. No commits, pushes, merges, deploys, network calls, or database writes were made.

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
?? backend/app/area_pilot/drug_poisoning.py
?? backend/app/area_pilot/drug_poisoning_api.py
?? backend/app/area_pilot/drug_poisoning_cli.py
?? backend/app/area_pilot/registry/nchs_drug_poisoning_2021.json
?? backend/tests/test_area_mortality_drug.py
?? backend/tests/test_area_mortality_drug_postgis.py
?? frontend/node_modules
```

*(Note: `frontend/node_modules` is a pre-existing symlink to `/home/john/chip-claude/frontend/node_modules`.)*

### Test commands and results

1. **Part A backend tests:**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_area_mortality_drug.py tests/test_area_mortality_drug_postgis.py tests/test_area_mortality_hds.py tests/test_area_lookup.py -q`
   - **Result:** `41 passed, 1 skipped`
     - `tests/test_area_mortality_drug.py`: 11 passed
     - `tests/test_area_mortality_drug_postgis.py`: 1 skipped (no active published `nchs_drug_poisoning_2021` release in `places_staging` yet)
     - `tests/test_area_mortality_hds.py`: 12 passed
     - `tests/test_area_lookup.py`: 18 passed (0 failed; `nchs_drug_poisoning` is county-only)

2. **Read-only dry-run against archived CSV (`data/ingest/nchs_drug_poisoning_county/rpvx-m2md.csv`):**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -c "..."` calling `drug_poisoning.retrieve(cfg, skip_fetch=True)`, `drug_poisoning_cli.validate_counts_and_checks(stats, cfg)`, and `drug_poisoning.classify` / `boundary_without_source` / `expected_observations` against 2024 TIGER county GEOIDs from `places_staging` (read-only `SELECT`).
   - **Result:** Passed — exact SHA-256 match (`822bae06e376f62947e745aa9dfba079d46e641ec8e6906449fa00cbff617b03`), 59,584 staged rows across all 19 years `2003`–`2021` (3,136 counties per year), Durham County (`37063`) 2021 check value verified (`23.87115`, 95% interval `22.12165`–`25.75957`), `0` unexplained rows, `0` duplicate GEOIDs, `0` range problems, and 3,122 published 2021 county observations (range `5.00205`–`164.57930`).

3. **Frontend tests and production build:**
   `cd frontend && npx vitest run src/pages/Places2025Pilot.test.jsx && npm run build`
   - **Result:** `47 passed (47)` in `src/pages/Places2025Pilot.test.jsx`; `vite build` succeeded cleanly (`dist/index.html`, `dist/assets/index-*.js`, `dist/assets/index-*.css`).

4. **MCP tests:**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv-mcp/bin/python -m pytest tests/test_mcp_*.py -q`
   - **Result:** `2 failed, 26 passed` (see Failures below)

5. **Community profile regression tests and snapshot diff:**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_community_api.py tests/test_community_state.py tests/test_community_charts_api.py -q`
   - **Result:** `15 passed`
   `git diff --exit-code docs/beta/contract-examples`
   - **Result:** Exit code `0` (byte-identical)

### Failures (outside owned files; not modified)

1. `backend/tests/test_mcp_integration.py::test_search_context_and_sources`
   - **Reason:** Hard-codes `assert len(sources.data['products']) == 12`; with `'nchs_drug_poisoning'` added to `PUBLIC_PRODUCTS`, `list_data_sources()` now returns `13` products.
2. `backend/tests/test_mcp_integration.py::test_http_client`
   - **Reason:** `FileNotFoundError: '.venv-mcp/bin/uvicorn'`. The test launches `.venv-mcp/bin/uvicorn` relative to the worktree's `backend/` directory, whereas `.venv-mcp` lives in `/home/john/chip-claude/backend/.venv-mcp`.

### Open questions / notes for Claude

- **Custom `ci95` label in `lookup.py`:** Contract §3 specifies that `nchs_drug_poisoning`'s uncertainty label reads `"95% interval from NCHS's model"` rather than `"95% confidence interval"`. Added `UNCERTAINTY_LABEL = "95% interval from NCHS's model"` on `drug_poisoning_api` and updated `lookup._row` to read `getattr(spec.api, 'UNCERTAINTY_LABEL', None) or '95% confidence interval'` so existing `ci95` products (`places`, `brfss`, `nci_cancer_mortality`) remain unchanged.
- **Unmatched 2021 county codes (`source_only`):** Of 3,136 rows in 2021, 3,122 match 2024 TIGER counties and 14 are staged as `source_only`: the 8 legacy Connecticut counties (`09001`–`09015`, reason `legacy_connecticut_county_code`) plus 6 pre-2024 legacy county codes (`02201`, `02232`, `02261`, `02270`, `02280`, and `46113`, reason `no_2024_boundary`). The 100 2024 TIGER counties absent from 2021 (9 Connecticut planning regions + 91 Puerto Rico municipios and newer AK/SD equivalents) read `not_in_release` at query time.
- **No open blockers for M4 ingest.**

## M2 (2026-11-21T02:04Z)

Implemented `nci_cancer_mortality` (NCI/CDC State Cancer Profiles death rates, 2020–2024: all sites, lung and bronchus, colon and rectum) across backend ingest/CLI/API/lookup/router/comparability, `/area/cancer-mortality` map page, and public MCP config. Reused helpers by import from `hds_mortality`, `hds_mortality_cli`, and `hds_mortality_api`. No commits, pushes, merges, deploys, network calls, or database writes were made.

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
?? backend/app/area_pilot/cancer_mortality.py
?? backend/app/area_pilot/cancer_mortality_api.py
?? backend/app/area_pilot/cancer_mortality_cli.py
?? backend/app/area_pilot/registry/nci_cancer_mortality_2020_2024.json
?? backend/tests/test_area_mortality_cancer.py
?? backend/tests/test_area_mortality_cancer_postgis.py
?? frontend/node_modules
```

*(Note: `frontend/node_modules` is a pre-existing symlink to `/home/john/chip-claude/frontend/node_modules`.)*

### Test commands and results

1. **Part A backend tests:**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_area_mortality_cancer.py tests/test_area_mortality_cancer_postgis.py tests/test_area_mortality_hds.py tests/test_area_lookup.py -q`
   - **Result:** `1 failed, 40 passed, 1 skipped`
     - `tests/test_area_mortality_cancer.py`: 11 passed
     - `tests/test_area_mortality_cancer_postgis.py`: 1 skipped (no active published `nci_cancer_mortality_2020_2024` release in `places_staging` yet)
     - `tests/test_area_mortality_hds.py`: 12 passed
     - `tests/test_area_lookup.py`: 17 passed, 1 failed (see Failures below)

2. **Read-only dry-run against archived CSVs (`data/ingest/nci_scp_mortality_2024/`):**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -c "..."` calling `cancer_mortality.retrieve(cfg, skip_fetch=True)` and `cancer_mortality_cli.validate_counts_and_checks(stats, cfg)`
   - **Result:** Passed — 6 files parsed (`all`, `lung`, `colorectal` county + state; `breast_female_*` and `prostate_*` ignored), 9,591 staged rows (`3,144` per county file, `53` per state file), exact SHA-256 match on all 6 files, exact suppressed county counts (`58` all, `418` lung, `943` colorectal; `0` in state files), Durham County (`37063`) check values verified (`132.6` / `127.2–138.2` all; `25.1` / `22.8–27.5` lung; `11.8` / `10.2–13.5` colorectal), and national (`00000`) values verified and confirmed identical between county and state files (`143.2` / `143–143.4` all; `30.2` / `30.2–30.3` lung; `12.7` / `12.7–12.8` colorectal).

3. **Frontend tests and production build:**
   `cd frontend && npx vitest run src/pages/Places2025Pilot.test.jsx && npm run build`
   - **Result:** `45 passed (45)` in `src/pages/Places2025Pilot.test.jsx`; `vite build` succeeded cleanly (`dist/index.html`, `dist/assets/index-*.js`, `dist/assets/index-*.css`).

4. **MCP tests:**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv-mcp/bin/python -m pytest tests/test_mcp_*.py -q`
   - **Result:** `2 failed, 26 passed` (see Failures below)

5. **Community profile regression tests and snapshot diff:**
   `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_community_api.py tests/test_community_state.py tests/test_community_charts_api.py -q`
   - **Result:** `1 failed, 14 passed` (see Failures below)
   `git diff --exit-code docs/beta/contract-examples`
   - **Result:** Exit code `0` (byte-identical)

### Failures (outside owned files; not modified)

1. `backend/tests/test_area_lookup.py::test_level_filter_returns_only_products_published_at_that_level`
   - **Reason:** Hard-codes the state-level product set (`{'acs', 'acs_profile', 'brfss', 'cms_gv', 'fema_nri', 'cdc_hds_mortality'}`), which now also includes `'nci_cancer_mortality'`.
2. `backend/tests/test_mcp_integration.py::test_search_context_and_sources`
   - **Reason:** Hard-codes `assert len(sources.data['products']) == 11`; with `'nci_cancer_mortality'` added to `PUBLIC_PRODUCTS`, `list_data_sources()` now returns `12` products.
3. `backend/tests/test_mcp_integration.py::test_http_client`
   - **Reason:** `FileNotFoundError: '.venv-mcp/bin/uvicorn'`. The test launches `.venv-mcp/bin/uvicorn` relative to the worktree's `backend/` directory, whereas `.venv-mcp` lives in `/home/john/chip-claude/backend/.venv-mcp`.
4. `backend/tests/test_community_charts_api.py::test_shapes_and_all_current_measures`
   - **Reason:** `cdc_hds_mortality_2022_2024` is now published in `places_staging`, while line 55 of `test_community_charts_api.py` only excludes `{'cdc_svi', 'fema_nri'}` when comparing `/charts` measures to `lookup.area_values` (pre-M6 hard-coded exclusion set; will apply to `nci_cancer_mortality` too once published).

### Open questions / notes for Claude

- **Non-`SS000` FIPS codes in `*_state.csv` (`02900` Alaska, `11001` DC, `72001` Puerto Rico):** All three `*_state.csv` files have 53 rows: `00000` (United States), 49 states encoded as `SS000`, plus `"Alaska"` (`02900`), `"District of Columbia"` (`11001`), and `"Puerto Rico"` (`72001`). Following the contract strictly (`SS000` → state `SS`, no unapproved crosswalks, and never classifying state-file rows as counties so they cannot collide with `*_county.csv`), `cancer_mortality.classify` currently stages `02900`, `11001`, and `72001` from `*_state.csv` as `source_only` (`no_2024_boundary`), matching 49 states. **Question before M4 ingest:** Should we add an explicit NCI state-file code map (`{'02900': '02', '11001': '11', '72001': '72'}`) so Alaska, DC, and Puerto Rico publish at state level (all 52 2024 TIGER states), or keep them `source_only`?
- **Puerto Rico commonwealth row (`72001`) in `*_county.csv`:** Each `*_county.csv` contains one `72*` row: `"Puerto Rico",72001` with island-wide totals (`98.6`, 5,364 annual deaths for all sites — identical to `all_state.csv`). In 2024 TIGER, `72001` is Adjuntas Municipio, PR. To avoid falsely assigning all of Puerto Rico's cancer mortality to Adjuntas Municipio, `cancer_mortality.classify` stages `code == '72001'` with `County == 'Puerto Rico'` as `source_only` (`puerto_rico_territory_aggregate_not_county`).
- **Duplicate `00000` (`United States`) rows across `*_state.csv` and `*_county.csv`:** Both files include `00000` with identical rates and 95% CIs. Both rows are staged (`stage_nci_cancer_mortality` PK includes `source_file`); `*_state.csv`'s `00000` is published as `national_reference` (`US`), `*_county.csv`'s `00000` is staged as `source_only` (`duplicate_national_row_in_county_file`), and `validate_counts_and_checks` verifies that both files report the exact same national rate and 95% CI.
- **Other legacy/synthetic county codes in `*_county.csv`:** Beyond the 8 legacy Connecticut counties (`09001`–`09015`, `legacy_connecticut_county_code`), `*_county.csv` contains `02261` (Valdez-Cordova Census Area, AK) and `51917` (Bedford City and County, VA), both staged as `source_only` (`no_2024_boundary`).

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
