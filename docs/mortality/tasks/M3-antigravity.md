# Task M3 (Antigravity): NCHS drug poisoning mortality as a shared area product

Assigned by Claude on 2026-11-21.
- Work in `/home/john/chip-agy-mort` on branch `agy/mortality`.
- The migration `c3e7a1f5b9d2_add_mortality_area.py` is already in the branch and applied to `places_staging`.
- The source file is already archived in `data/ingest/nchs_drug_poisoning_county/` in your worktree.

**You own, for this task only:**
- New files:
  - `backend/app/area_pilot/drug_poisoning.py`, `drug_poisoning_api.py`, and `drug_poisoning_cli.py`
  - `backend/app/area_pilot/registry/nchs_drug_poisoning_2021.json`
- Additions only (no rewrites) to:
  - `backend/app/area_pilot/lookup.py`, `router.py`, and `registry/comparability.json`
  - `backend/app/mcp_server/config.py`
  - `frontend/src/main.jsx`, `frontend/src/utils/routeResolver.js`, `frontend/src/pages/Places2025Pilot.jsx`, and its `.test.jsx`
- New tests: `backend/tests/test_area_mortality_drug.py` and `test_area_mortality_drug_postgis.py`.
- `docs/mortality/status/antigravity.md`.

Edit nothing else. If a test outside these paths fails because of your change, report it; don't fix it.

**Rules:**
- Do not commit, push, merge, deploy, or use sudo.
- Make no network calls.
- Write no database rows. Unit tests use small fixtures. The PostGIS test only reads `places_staging` and skips cleanly when no release exists.
- Never edit the project diary, the handbook, `AGENTS.md`, or `alembic/`.
- Write normally formatted source: JSX broken across lines, unminified CSS, and Python lines of about 120 characters or fewer.

## Read first
- [CONTRACT.md](../CONTRACT.md): the shared rules and §3. Measure IDs, labels, status mapping, limitations, and boundaries are fixed there.
- Your M1 files (`hds_mortality*.py`, already in this branch) are the closest template; reuse their helpers by import where you can, rather than copying. CMS GV remains the reference, (M3 is county only). Copy its structure file for file and keep the same function names:
  - `backend/app/area_pilot/cms_gv.py`, `cms_gv_api.py`, `cms_gv_cli.py`, and `registry/cms_om_gv.json`
  - `backend/tests/test_area_cms_gv.py` and `test_area_cms_gv_postgis.py`
- For the Connecticut rule, see `LEGACY_CT_COUNTIES` in `svi.py`.
- `backend/alembic/versions/c3e7a1f5b9d2_add_mortality_area.py`, for the tables `stage_nchs_drug_poisoning` and `observation_nchs_drug_poisoning`.

## Part A: backend
- `drug_poisoning.py`: parse `rpvx-m2md.csv` (`utf-8-sig`), zero-pad `FIPS` to 5 digits, and stage every row for 2003–2021 (`source_period` = the year). Publish observations for 2021 only, county level only, with `ci_low`/`ci_high` from the confidence-limit columns. Any blank or non-positive 2021 value stops the run. Write `fetch` for the data.cdc.gov CSV but do not run it.
- `drug_poisoning_cli.py`: the same subcommands as `hds_mortality_cli.py`, with `--skip-fetch`. Validation checks the contract counts and the Durham County (37063) check value.
- `drug_poisoning_api.py`: the same interface as `hds_mortality_api.py`.
- `lookup.py`: `Spec('nchs_drug_poisoning', …)` as the contract states (uncertainty `ci95` with `ci_low`/`ci_high`), `MISSING_STATUS` → `not_in_release`. No `SOURCE_CREDITS` entry.
- `router.py` and `comparability.json`: entries beside `cdc_hds_mortality`.
- Tests: parser edge cases (suppressed row, bad token, zero rate, legacy Connecticut code, national row if the product has one) and API metadata. Run:
  `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_area_mortality_drug.py tests/test_area_mortality_drug_postgis.py tests/test_area_mortality_hds.py tests/test_area_lookup.py -q`

## Part B: map and MCP (only after Part A passes)
- Route `/area/drug-poisoning-mortality` rendering `<Places2025Pilot dataset="drug_poisoning" />`, added wherever `hds_mortality` appears, default measure `drug_poisoning_death_rate`, the contract's menu label, and an explanation drawn from the contract's limitations. Run `cd frontend && npx vitest run src/pages/Places2025Pilot.test.jsx && npm run build`.
- MCP: add `'nchs_drug_poisoning'` to `PUBLIC_PRODUCTS` (the RULES sentence already exists). Run `pytest tests/test_mcp_*.py -q`.
- Profiles must not change: run the three community test files from M1 and `git diff --exit-code docs/beta/contract-examples`.

## Report
Add a `## M3` section to `docs/mortality/status/antigravity.md` with files changed, every test command and count, failures with reasons, and open questions. Then stop.
