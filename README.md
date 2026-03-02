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

Equivalent module entrypoints:

```bash
cd backend
python -m app.cms.ingest.gv_ingest --path "../data/2014-2023 Medicare Fee-for-Service Geographic Variation Public Use File.csv"
python -m app.cms.ingest.ssp_ingest --path "../data/County_Level_FFS_Data_for_Shared_Savings_Program_Benchmark_PUF_2024_01_01_Offset_Assignables_2025 Starters.csv"
```

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
