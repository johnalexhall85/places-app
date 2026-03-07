# Backend Script Notes

## Schema Mapping Env Vars

Defaults:
- `PLACES_SCHEMA=public`
- `ACS_SCHEMA=public`
- `SVI_SCHEMA=public`
- `HRSA_SCHEMA=public`
- `CMS_SCHEMA=cms`
- `USDA_FOOD_ACCESS_SCHEMA=usda_food_access`
- `USDA_FOOD_ENV_SCHEMA=usda_food_env`
- `FEMA_NRI_SCHEMA=fema_nri`

Verify resolved mapping and table access:

```bash
python backend/scripts/verify_schema_mapping.py
```

## CMS Ingestion (Schema `cms`)

CMS tables are isolated in schema `cms` (controlled by `CMS_SCHEMA`, default `cms`).

Ingest Geographic Variation PUF:

```bash
python backend/scripts/ingest_cms_gv.py \
  --path "./data/2014-2023 Medicare Fee-for-Service Geographic Variation Public Use File.csv"
```

Ingest SSP County FFS PUF:

```bash
python backend/scripts/ingest_cms_ssp.py \
  --path "./data/County_Level_FFS_Data_for_Shared_Savings_Program_Benchmark_PUF_2024_01_01_Offset_Assignables_2025 Starters.csv"
```

Verify CMS tables exist:

```bash
python backend/scripts/verify_cms_tables.py
```

Equivalent module entrypoints:

```bash
cd backend
python -m app.cms.ingest.gv_ingest --path "../data/2014-2023 Medicare Fee-for-Service Geographic Variation Public Use File.csv"
python -m app.cms.ingest.ssp_ingest --path "../data/County_Level_FFS_Data_for_Shared_Savings_Program_Benchmark_PUF_2024_01_01_Offset_Assignables_2025 Starters.csv"

# USDA Food Access Research Atlas ingest (tract-level)
python -m app.usda_food_access.ingest

# USDA Food Environment Atlas ingest (county/state, July 2025)
python -m app.usda_food_env.ingest

# FEMA National Risk Index ingest (county + tract, December 2025)
# (run migrations first: cd backend && ./.venv/bin/alembic upgrade head)
python -m app.fema_nri.ingest --replace
```

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

`hpsa_domain_quartiles` is also rebuilt for `pc`, `mh`, and `dh` using only designated
counties with non-null `*_hpsa_score_max`, storing `q25`, `q50`, `q75`, `n_counties`,
and `as_of_date` for deterministic choropleth tiering.
