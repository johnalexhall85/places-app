# Places App

## Load county boundary polygons

Run the offline loader after applying migrations and configuring `DATABASE_URL`:

```bash
psql "$DATABASE_URL" -f backend/scripts/create_dim_county_boundary.sql
python backend/scripts/load_county_boundaries.py --db-url "$DATABASE_URL"
```

## Load census tract data

1. Apply migrations (creates `tract_shapes` and `tract_estimates`):

```bash
cd backend
source ../venv/bin/activate
alembic upgrade head
```

2. Download TIGER/Line 2020 tract ZIPs (single-state test run):

```bash
python backend/scripts/download_tiger_tracts.py --state 01
```

3. Import TIGER tract shapes into PostGIS:

```bash
python backend/scripts/import_tract_shapes.py --state 01
```

4. Ingest PLACES 2025 tract estimates CSV:

```bash
python backend/scripts/ingest_tract_estimates.py
```

For full national TIGER download/import, omit `--state` on both scripts.

## Preflight county CSV (2024 release)

Run read-only validation (no DB writes):

```bash
python backend/scripts/preflight_places_county_2024.py
```

Run preflight + write ingestion (uses same mapping/codepath):

```bash
python backend/scripts/preflight_places_county_2024.py --write
```

## Ask the map assistant (OpenRouter)

Set assistant config in `config/llm_settings.json` (this repo already gitignores `config/`):

```json
{
  "openrouter_api_key": "your_openrouter_api_key",
  "openrouter_model": "openai/gpt-5.2",
  "openrouter_base_url": "https://openrouter.ai/api/v1",
  "openrouter_timeout_seconds": 60.0,
  "openrouter_http_referer": "http://localhost:5173",
  "openrouter_x_title": "PLACES Next App",
  "openrouter_temperature": 0.0,
  "openrouter_max_tokens": 1400,
  "openrouter_tool_choice": "auto",
  "assistant_max_steps": 8,
  "assistant_format_retry_limit": 1,
  "assistant_system_prompt": ""
}
```

Then call:

```bash
curl -sS -X POST "http://localhost:8000/assistant/query" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "What is arthritis in Fulton County GA?",
    "context": {
      "measure_id": "ARTHRITIS",
      "year": 2023,
      "data_value_type_id": "CrdPrv",
      "zoom": 6,
      "bbox": [-85, 33, -84, 34],
      "active_layer": "county"
    }
  }'
```

## Report branding assets and cache

CHIP report branding assets are stored in:
- `backend/app/assets/brand/` (logos used by PDF rendering)
- `backend/app/assets/fonts/` (optional Inter / Source Sans 3 files for PDF typography)

Clear generated report caches:

```bash
cd backend
python -m app.scripts.clear_report_cache
```

Also clear cached chart PNGs (forces chart restyling on regeneration):

```bash
cd backend
python -m app.scripts.clear_report_cache --include-charts
```

## Ingest SVI time series (2018, 2020, 2022)

Use the multi-year ingester:

```bash
python backend/scripts/ingest_svi_years.py --years 2018 2020 --level both
```

See `backend/scripts/README.md` for additional options.
