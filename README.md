# Places App

## Load county boundary polygons

Run the offline loader after applying migrations and configuring `DATABASE_URL`:

```bash
psql "$DATABASE_URL" -f backend/scripts/create_dim_county_boundary.sql
python backend/scripts/load_county_boundaries.py --db-url "$DATABASE_URL"
```
