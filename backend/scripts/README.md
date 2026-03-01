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

## Ingest HRSA HPSA (PC/MH/DH) + rebuild county summary

Load designation-level files and rebuild `county_hpsa_summary`:

```bash
python backend/scripts/ingest_hpsa.py \
  --pc /mnt/data/BCD_HPSA_FCT_DET_PC.csv \
  --mh /mnt/data/BCD_HPSA_FCT_DET_MH.csv \
  --dh /mnt/data/BCD_HPSA_FCT_DET_DH.csv \
  --rebuild-summary
```

Optional flags:

```bash
# clear existing raw staging table before loading
python backend/scripts/ingest_hpsa.py ... --truncate-staging

# skip summary rebuild
python backend/scripts/ingest_hpsa.py ... --no-rebuild-summary
```

`county_hpsa_summary` includes coverage percentages (`*_coverage_pct`) computed as:
- denominator: county adult 18+ population when available, otherwise total population
- source: `v_county_population` view (from `dim_county`)
- formula: `(population_covered / denominator) * 100`, rounded to 3 decimals, clamped to `[0, 100]`
- aggregation method: `MAX` designated population per county/type (conservative for overlap risk)
- method metadata fields: denominator source/type, overlap caveat, pct definition, and per-type method text
