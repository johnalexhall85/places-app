# Places App

This repository contains a local health mapping app with:
- Frontend: React + Vite on `http://localhost:5173`
- Backend: FastAPI on `http://localhost:8000`
- Database: PostGIS/Postgres (Docker)

The setup below is aimed at first run after cloning or downloading from GitHub.

## Prerequisites

- `git`
- `docker` and `docker compose`
- `python` 3.10+
- `node` 18+ and `npm`
- Optional: `psql` (used by one SQL helper step)

## Quickstart (from fresh clone)

### 1) Start PostGIS

From repo root:

```bash
docker compose -f infra/docker-compose.yml up -d
```

### 2) Set up and run backend

In terminal 1:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

### 3) Set up and run frontend

In terminal 2:

```bash
cd frontend
npm install
npm run dev
```

## Verify it works

In terminal 3:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

Then open `http://localhost:5173` in your browser.

## Optional: one-command startup (`dev-start.sh`)

If you prefer:

```bash
./dev-start.sh
```

Important constraints:
- `backend/.venv` must already exist (the script exits if it does not).
- The script checks for `docker-compose.yml` at repo root; this repo's compose file is at `infra/docker-compose.yml`.
- Run `docker compose -f infra/docker-compose.yml up -d` manually first for reliable DB startup.

## Optional: assistant (OpenRouter) setup

The app can run without assistant config. Assistant features are optional.

Create `config/llm_settings.json` (this path is gitignored) with your OpenRouter key and optional overrides:

```json
{
  "openrouter_api_key": "your_openrouter_api_key",
  "openrouter_model": "openai/gpt-5.2",
  "openrouter_base_url": "https://openrouter.ai/api/v1",
  "openrouter_http_referer": "http://localhost:5173",
  "openrouter_x_title": "PLACES App"
}
```

Minimal test request:

```bash
curl -sS -X POST "http://localhost:8000/assistant/query" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "What is arthritis in Fulton County GA?",
    "context": {
      "measure_id": "ARTHRITIS",
      "year": 2023,
      "data_value_type_id": "CrdPrv"
    }
  }'
```

## Appendix: optional data loading (for non-empty map and richer results)

Set DB URL for ingestion scripts:

```bash
export DATABASE_URL=postgresql+psycopg://places:places@localhost:5432/places
```

Optional schema mapping overrides (defaults preserve current behavior):

```bash
export PLACES_SCHEMA=public
export ACS_SCHEMA=public
export SVI_SCHEMA=public
export HRSA_SCHEMA=public
export CMS_SCHEMA=cms
export USDA_FOOD_ACCESS_SCHEMA=usda_food_access
export USDA_FOOD_ENV_SCHEMA=usda_food_env
export FEMA_NRI_SCHEMA=fema_nri
export ANALYTICS_SCHEMA=analytics
```

Quick schema mapping verification:

```bash
python backend/scripts/verify_schema_mapping.py
```

### County boundaries

```bash
psql "$DATABASE_URL" -f backend/scripts/create_dim_county_boundary.sql
python backend/scripts/load_county_boundaries.py --db-url "$DATABASE_URL"
```

### County PLACES preload (2024)

```bash
python backend/scripts/preflight_places_county_2024.py --write
```

### Advanced ingestion shortcuts

Tract shapes + tract estimates:

```bash
python backend/scripts/download_tiger_tracts.py --state 01
python backend/scripts/import_tract_shapes.py --state 01
python backend/scripts/ingest_tract_estimates.py --db-url "$DATABASE_URL"
```

SVI time series:

```bash
python backend/scripts/ingest_svi_years.py --years 2018 2020 2022 --level both
```

HPSA county summary:

```bash
python backend/scripts/ingest_hpsa.py \
  --pc data/BCD_HPSA_FCT_DET_PC.csv \
  --mh data/BCD_HPSA_FCT_DET_MH.csv \
  --dh data/BCD_HPSA_FCT_DET_DH.csv \
  --rebuild-summary
```

CMS ingests (tables are isolated in schema `cms`):

```bash
python backend/scripts/ingest_cms_gv.py \
  --path "./data/2014-2023 Medicare Fee-for-Service Geographic Variation Public Use File.csv"

python backend/scripts/ingest_cms_ssp.py \
  --path "./data/County_Level_FFS_Data_for_Shared_Savings_Program_Benchmark_PUF_2024_01_01_Offset_Assignables_2025 Starters.csv"

python backend/scripts/verify_cms_tables.py
```

TAGGS redo CSV rebuild ingest (multi-OPDIV exports in `data/taggs/redo`):

```bash
python backend/scripts/ingest_taggs_redo.py \
  --input-dir ./data/taggs/redo \
  --drop-and-recreate \
  --rebuild-summaries \
  --rebuild-can-table \
  --verbose
```

Reference:

- `backend/app/taggs/CSV_INGEST.md`

USAspending CDC contract prime-transaction ingest (raw immutable rows plus first-pass classification support in `data/usaspending/contracts`):

```bash
python backend/scripts/ingest_usaspending_contracts.py \
  --input-dir ./data/usaspending/contracts \
  --drop-and-recreate \
  --rebuild-summaries \
  --verbose
```

Contract rows are ingested even though CDC Funding Profiles generally exclude contract expenditures, because the CDC profile methodology explicitly includes vaccine purchases provided through the Vaccines for Children program. CHIP therefore preserves every raw contract transaction unchanged and applies profile-relevance logic only in the derived enrichment and summary layers.

Observed federal account lookup / classification rebuild (additive `recon` layer only):

```bash
cd backend
python scripts/build_federal_account_lookup.py \
  --reseed-from-observed \
  --rebuild-observations \
  --rebuild-classification \
  --export-review-csv \
  --verbose
```

Why CHIP starts with observed federal account symbols instead of the full public account universe:

- the lookup is seeded only from account symbols actually observed in CHIP's CDC USAspending contracts and assistance data
- this keeps the workflow deterministic, reviewable, and tightly scoped to the funding sources CHIP needs
- raw USAspending and TAGGS tables stay unchanged; only additive lookup tables, observation summaries, and derived views are built at this stage
- if no local account metadata CSV is available, the lookup still builds from observed symbols alone and remains ready for later enrichment

Outputs:

- `recon.federal_account_lookup`
- `recon.federal_account_observations`
- `recon.federal_account_classification_rules`
- `recon.contract_transaction_accounts`
- `recon.assistance_transaction_accounts`
- `recon.federal_account_review_export`
- optional review export at `data/usaspending/review/federal_account_review.csv`

This step prepares the federal account layer for later CDC-profile-aligned normalization and CDC funding profile reconstruction. It does not build final normalization on its own.

CDC profile-scope reconstruction rebuild (additive derived layer only):

```bash
cd backend
./.venv/bin/alembic upgrade head
python scripts/build_profile_scope_layer.py --verbose
```

This layer classifies USAspending assistance and contract rows into a conservative CDC Funding Profiles candidate universe. It keeps raw source tables untouched, treats contracts as mostly out of scope except likely VFC procurement, uses the federal-account lookup as a core signal, preserves uncertain rows instead of forcing overconfident binary decisions, and writes the summary report to `data/recon/profile_scope_build_summary.json`.

CDC Funding Profiles calibration and reconciliation rebuild:

```bash
cd backend
./.venv/bin/alembic upgrade head
python scripts/build_profile_calibration_layer.py \
  --fiscal-years 2020 2021 2022 2023 2024 2025 2026 \
  --source-system usaspending \
  --include-taggs \
  --rebuild-normalized-table \
  --export-summary \
  --verbose
```

This step sits on top of `recon.profile_scope_transactions` and related derived layers. It compares reconstructed profile-scope state totals to observed CDC Funding Profiles FY2020-FY2023, writes state-year residuals and driver diagnostics, refreshes the canonical `recon.normalized_state_funding` map table, and exports `data/recon/profile_calibration_summary.json`. CDC profile totals are used only as calibration references; CHIP does not copy them into normalized totals.

Outputs:

- `recon.profile_calibration_cdc_reference` (view)
- `recon.profile_scope_transaction_diagnostics` (view)
- `recon.profile_calibration_usaspending_state_year_support` (view)
- `recon.profile_calibration_taggs_state_year_support` (view)
- `recon.profile_reconciliation_state_year`
- `recon.profile_reconciliation_driver_breakdown`
- `recon.profile_reconciliation_summary`
- `recon.normalized_state_funding`

CHIP v1.1 emergency-classification layer:

```bash
cd backend
./.venv/bin/alembic upgrade head
export CDC_STATE_PROFILE_RAW_SOURCE_VERSION=v1_1_emergency_classification
python scripts/export_chip_emergency_classification.py \
  --output-dir ../exports/chip_v11_emergency
```

This additive layer builds versioned `analytics.*` recipient-classification, transaction-classification, state-profile, centralized-funding, and validation views on top of `recon.profile_scope_transactions`.
It is intentionally a partial rollout:

- raw state-profile totals can opt into `v1_1_emergency_classification`
- `chip_normalized` remains on the legacy v1 normalization layer

See [CHIP_V11_EMERGENCY_CLASSIFICATION.md](/home/john/places-app/CHIP_V11_EMERGENCY_CLASSIFICATION.md) for the methodology note, object list, rollout boundary, PHFE handling, and validation views.

Equivalent module entrypoints:

```bash
cd backend
python -m app.cms.ingest.gv_ingest --path "../data/2014-2023 Medicare Fee-for-Service Geographic Variation Public Use File.csv"
python -m app.cms.ingest.ssp_ingest --path "../data/County_Level_FFS_Data_for_Shared_Savings_Program_Benchmark_PUF_2024_01_01_Offset_Assignables_2025 Starters.csv"

# USDA Food Access (tract-level atlas)
python -m app.usda_food_access.ingest

# USDA Food Environment Atlas 2025 (county/state map dataset)
python -m app.usda_food_env.ingest

# FEMA National Risk Index (county + tract map dataset)
# (run migrations first: cd backend && ./.venv/bin/alembic upgrade head)
python -m app.fema_nri.ingest --replace
```

USDA Food Environment map rendering behavior:
- County choropleth by default (`/api/usda/food-environment/map`)
- Automatic state overlay for state-level variables marked `*` in USDA metadata
- Legend endpoint: `/api/usda/food-environment/legend`

Verify CMS endpoints:

```bash
curl "http://localhost:8000/cms/gv/geo?level=county&year=2023&age_level=All&measure_id=BENES_TOTAL_CNT"
curl "http://localhost:8000/cms/gv/county/01001?year=2023&age_level=All&measure_ids=BENES_TOTAL_CNT,BENES_FFS_CNT"
curl "http://localhost:8000/cms/ssp/county/01001?year=2024&enrollment_type=agdu&assign_window=offset&measure_ids=PER_CAPITA_EXP,AVG_RISK_SCORE"
```

For full script options and expected input files, see `backend/scripts/README.md`.

## Troubleshooting

- DB connection errors:
  - Verify Docker DB is running: `docker ps`
  - Verify `DATABASE_URL` if you overrode defaults.
- Backend dependency errors:
  - Activate `backend/.venv` and rerun `pip install -r backend/requirements.txt`.
- Frontend cannot reach API:
  - Confirm backend is running on port `8000` and frontend on `5173`.
- Map loads but looks empty:
  - Ingest optional data from the appendix sections above.

## Validation checklist (README accuracy)

1. Fresh-clone simulation:
   - Follow quickstart steps on a clean checkout and verify both services start.
2. Health check validation:
   - Confirm `GET /health` returns 200 with `{"status":"ok"}`.
3. Frontend integration:
   - Confirm app loads at `http://localhost:5173` and successfully calls backend at `http://localhost:8000`.
4. Optional script validation:
   - Confirm `dev-start.sh` behavior matches caveats above (`backend/.venv` required; compose file path caveat).
5. Optional data validation:
   - Run county boundary + county preload commands and verify data-backed endpoints return populated results.

## Assumptions and defaults

1. This README targets macOS/Linux shell usage. Windows users should use WSL or adapt commands.
2. Manual startup commands are canonical for first run and troubleshooting.
3. Assistant setup is optional and not required for core app startup.
4. Advanced ingestion details are retained in this README as appendix material.
5. Default local DB URL is `postgresql+psycopg://places:places@localhost:5432/places`.
