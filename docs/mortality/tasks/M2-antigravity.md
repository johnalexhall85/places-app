# Task M2 (Antigravity): NCI cancer mortality as a shared area product

Assigned by Claude on 2026-11-21.
- Work in `/home/john/chip-agy-mort` on branch `agy/mortality`.
- The migration `c3e7a1f5b9d2_add_mortality_area.py` is already in the branch and applied to `places_staging`.
- The source files are already archived in `data/ingest/nci_scp_mortality_2024/` in your worktree.

**You own, for this task only:**
- New files:
  - `backend/app/area_pilot/cancer_mortality.py`, `cancer_mortality_api.py`, and `cancer_mortality_cli.py`
  - `backend/app/area_pilot/registry/nci_cancer_mortality_2020_2024.json`
- Additions only (no rewrites) to:
  - `backend/app/area_pilot/lookup.py`, `router.py`, and `registry/comparability.json`
  - `backend/app/mcp_server/config.py`
  - `frontend/src/main.jsx`, `frontend/src/utils/routeResolver.js`, `frontend/src/pages/Places2025Pilot.jsx`, and its `.test.jsx`
- New tests: `backend/tests/test_area_mortality_cancer.py` and `test_area_mortality_cancer_postgis.py`.
- `docs/mortality/status/antigravity.md`.

Edit nothing else. If a test outside these paths fails because of your change, report it; don't fix it.

**Rules:**
- Do not commit, push, merge, deploy, or use sudo.
- Make no network calls.
- Write no database rows. Unit tests use small fixtures. The PostGIS test only reads `places_staging` and skips cleanly when no release exists.
- Never edit the project diary, the handbook, `AGENTS.md`, or `alembic/`.
- Write normally formatted source: JSX broken across lines, unminified CSS, and Python lines of about 120 characters or fewer.

## Read first
- [CONTRACT.md](../CONTRACT.md): the shared rules and §2. Measure IDs, labels, status mapping, limitations, and boundaries are fixed there.
- Your M1 files (`hds_mortality*.py`, already in this branch) are the closest template; reuse their helpers by import where you can, rather than copying. CMS GV remains the reference, which also has national, state, and county rows. Copy its structure file for file and keep the same function names:
  - `backend/app/area_pilot/cms_gv.py`, `cms_gv_api.py`, `cms_gv_cli.py`, and `registry/cms_om_gv.json`
  - `backend/tests/test_area_cms_gv.py` and `test_area_cms_gv_postgis.py`
- For the Connecticut rule, see `LEGACY_CT_COUNTIES` in `svi.py`.
- `backend/alembic/versions/c3e7a1f5b9d2_add_mortality_area.py`, for the tables `stage_nci_cancer_mortality` and `observation_nci_cancer_mortality`.

## Part A: backend
- `cancer_mortality.py`: parse the six `<site>_county.csv` / `<site>_state.csv` files for `all`, `lung`, and `colorectal` (latin-1). Find the header row starting `County,FIPS` or `State,FIPS`, read data rows until the first blank line, and ignore the footnotes. Check the title line reads `<Site>, 2020-2024`. Map `00000` → national `US`, `SS000` → state, else county. Stage every data row; `source_file` is the file name, `source_period` `2020–2024`. Store `ci_low`/`ci_high` from the CI columns; a suppressed row has NULL value and NULL interval. Do not stage or publish `breast_female_*` or `prostate_*`. Write `fetch` for the contract URLs but do not run it.
- `cancer_mortality_cli.py`: the same subcommands as `hds_mortality_cli.py`, with `--skip-fetch`. Validation checks the contract counts and the Durham County (37063) check value.
- `cancer_mortality_api.py`: the same interface as `hds_mortality_api.py`.
- `lookup.py`: `Spec('nci_cancer_mortality', …)` as the contract states (uncertainty `ci95` with `ci_low`/`ci_high`), `MISSING_STATUS` → `not_in_release`. No `SOURCE_CREDITS` entry.
- `router.py` and `comparability.json`: entries beside `cdc_hds_mortality`.
- Tests: parser edge cases (suppressed row, bad token, zero rate, legacy Connecticut code, national row if the product has one) and API metadata. Run:
  `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_area_mortality_cancer.py tests/test_area_mortality_cancer_postgis.py tests/test_area_mortality_hds.py tests/test_area_lookup.py -q`

## Part B: map and MCP (only after Part A passes)
- Route `/area/cancer-mortality` rendering `<Places2025Pilot dataset="cancer_mortality" />`, added wherever `hds_mortality` appears, default measure `cancer_death_rate_all`, the contract's menu label, and an explanation drawn from the contract's limitations. Run `cd frontend && npx vitest run src/pages/Places2025Pilot.test.jsx && npm run build`.
- MCP: add `'nci_cancer_mortality'` to `PUBLIC_PRODUCTS` (the RULES sentence already exists). Run `pytest tests/test_mcp_*.py -q`.
- Profiles must not change: run the three community test files from M1 and `git diff --exit-code docs/beta/contract-examples`.

## Report
Add a `## M2` section to `docs/mortality/status/antigravity.md` with files changed, every test command and count, failures with reasons, and open questions. Then stop.
