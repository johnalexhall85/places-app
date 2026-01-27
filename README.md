# Places App

## Load county boundary polygons

Run the offline loader after applying migrations and configuring `DATABASE_URL`:

```bash
python backend/scripts/load_county_boundaries.py --db-url "$DATABASE_URL"
```
