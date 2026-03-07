# FEMA NRI Data Discovery Notes

Date: 2026-03-05

## Source directories inspected

- `data/NRI_GDB_Counties/NRI_GDB_Counties.gdb`
- `data/NRI_GDB_CensusTracts/NRI_GDB_CensusTracts.gdb`
- `data/NRI_GDB_States/NRI_GDB_States.gdb`
- `data/NRI_GDB_Counties/NRIDataDictionary.csv`

## Layer discovery (deterministic)

### Counties GDB

- Feature class used: `NRI_Counties`
- Geometry type: `MultiPolygon`
- Feature count: `3232`
- CRS: `EPSG:3857`

Additional table present: `NRI_HazardInfo` (18 hazards and field-prefix mapping metadata).

### Census Tracts GDB

- Feature class used: `NRI_CensusTracts`
- Geometry type: `MultiPolygon`
- Feature count: `85154`
- CRS: `EPSG:3857`

Additional table present: `NRI_HazardInfo`.

### States GDB

- Feature class present: `NRI_States` (`56` features, `MultiPolygon`, `EPSG:3857`).
- State feature rendering is not exposed in current map UI scope.

## Geographic key fields found

### County layer keys

- `STATEFIPS` (2-digit)
- `COUNTYFIPS` (3-digit)
- `STCOFIPS` (5-digit county GEOID/FIPS)
- `NRI_ID` (county-prefixed identifier, e.g., `C01001`)

### Tract layer keys

- `STATEFIPS` (2-digit)
- `COUNTYFIPS` (3-digit)
- `STCOFIPS` (5-digit county GEOID/FIPS)
- `TRACT` (6-digit tract code)
- `TRACTFIPS` (11-digit tract GEOID/FIPS)
- `NRI_ID` (tract-prefixed identifier, e.g., `T01001020100`)

## Key integrity checks

- County null checks: `STCOFIPS`, `STATEFIPS`, `COUNTYFIPS` had no nulls in source.
- Tract null checks: `TRACTFIPS`, `STCOFIPS` had no nulls in source.
- Distinct IDs:
  - County `STCOFIPS`: `3232` distinct (matches row count).
  - Tract `TRACTFIPS`: `85154` distinct (matches row count).

## Geometry validity checks (source)

Using `ST_IsValid(Shape)` against source geometries:

- County invalid count: `77`
- Tract invalid count: `82`

Ingestion applies `ST_MakeValid` and preserves rows (no silent dropping).

## Field catalog findings

- Data dictionary file rows: `479`
- Data dictionary columns: `Sort`, `Field Name`, `Field Alias`, `Type`, `Length`, `Relevant Layer`, `Metric Type`, `Version`, `Version Date`

### Cross-layer field overlap

- County fields: `466`
- Tract fields: `468`
- Common fields across county + tract: `466`
- Tract-only fields: `TRACT`, `TRACTFIPS`
- County-only fields: none identified

## UI exposure strategy

### Exposed as selectable measures

Curated measure catalog is in `backend/app/fema_nri/measure_catalog.json` and includes grouped measures for:

- Composite risk
- Expected annual loss
- Community factors
- Hazard-specific risk (18 hazards)

Each measure records friendly labels, descriptions, units, value type, legend mode, tooltip formatter, and supported levels.

### Hidden/deprioritized from UI

- Geometry and administrative shape-only fields
- Duplicate/technical intermediate fields that are hard to explain in a lightweight legend
- State-only or state-percentile-heavy fields not required for county/tract map UX

## Feature classes used by ingestion

- Counties: `NRI_Counties` -> target table `fema_nri.nri_county`
- Tracts: `NRI_CensusTracts` -> target table `fema_nri.nri_tract`

State layer is not loaded into map-serving tables in this phase.
