# Backend Script Notes

## Ingest SVI Multiple Years (2018, 2020, 2022)

`ingest_svi_years.py` loads county and tract SVI CSVs into:
- `svi_measures`
- `svi_estimates_county`
- `svi_estimates_tract`

It supports chunked ingest, canonical year-specific column normalization, and idempotent upserts.

### Examples

Ingest 2018 + 2020 for both county and tract:

```bash
python backend/scripts/ingest_svi_years.py --years 2018 2020 --level both
```

Ingest tract only:

```bash
python backend/scripts/ingest_svi_years.py --years 2018 2020 --level tract
```

Re-run including 2022:

```bash
python backend/scripts/ingest_svi_years.py --years 2018 2020 2022 --level both
```

Use an explicit data directory and DB URL:

```bash
python backend/scripts/ingest_svi_years.py \
  --years 2018 2020 \
  --level county \
  --data-dir /data \
  --db-url "$DATABASE_URL"
```
