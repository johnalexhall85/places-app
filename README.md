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
