# CDC Funding API v1

The CDC Funding API v1 is a read-only annual funding API under:

```text
/api/cdc-funding/v1
```

It is intentionally separate from the existing CDC Funding Map API. All funding values come exclusively from the ingested CDC funding annual account-summary table:

```text
cdc_funding.cdc_funding_account_annual
```

Available fiscal-year metadata is checked against:

```text
cdc_funding.cdc_funding_import_runs
```

The API does not query existing CDC Funding Map tables, geographic aggregates, map classification services, legacy funding datasets, award-level rows, source CSV files, external APIs, or USAspending directly.

## Scope

All endpoints accept an optional `scope` query parameter:

- `scope=all_accounts` is the default and preserves the original all-account annual account-summary behavior.
- `scope=cdc_funding_profiles` limits annual rows to classifications that are exactly mapped to CDC Funding Profile budget categories.

The standalone `/cdc-funding` page explicitly requests `scope=all_accounts`. It represents every federal account row
in the ingested CDC-awarded annual account-summary dataset for the selected fiscal year. CDC Funding Profile mapping is
not an inclusion requirement for that page: mapped and unmapped account-classification combinations are included.

The mapped scope matches rows by this composite key:

```text
fiscal_year + federal_account_symbol + grant_or_contract + emergency
```

Only mapping rows with `mapping_status = 'Mapped'` are included. Account symbol alone is not sufficient: a federal account can have some included combinations and other excluded combinations in the same fiscal year.

## Fiscal Years

```http
GET /api/cdc-funding/v1/fiscal-years
```

Returns fiscal years with both:

- A completed CDC funding import run.
- Current annual account-summary rows.

Years are sorted descending, and only the latest is marked `is_latest`.

```json
{
  "scope": "all_accounts",
  "fiscal_years": [
    {
      "fiscal_year": 2026,
      "is_latest": true
    }
  ],
  "latest_fiscal_year": 2026
}
```

If no years are available, this endpoint returns a successful response with an empty list and `latest_fiscal_year: null`.

FY2021 through FY2026 are currently available under `scope=all_accounts`, and FY2026 is currently latest. The page does
not hardcode those values; it uses this endpoint to determine the selector options and latest year dynamically.

## Overview

```http
GET /api/cdc-funding/v1/overview?fiscal_year=2023
```

The `fiscal_year` query parameter is optional. When omitted, the latest completed fiscal year is used. Pass
`scope=cdc_funding_profiles` to return only CDC Funding Profile-mapped classifications:

```http
GET /api/cdc-funding/v1/overview?fiscal_year=2023&scope=cdc_funding_profiles
```

The response contains annual obligations for:

- Emergency grants
- Emergency contracts
- Nonemergency grants
- Nonemergency contracts
- Combined emergency/nonemergency and grant/contract totals

Money values are decimal strings with exactly two decimal places. Percentages are decimal strings with four decimal places. Negative obligations are retained in sums.

For `scope=all_accounts`, overview totals come from all annual account-summary rows for the selected fiscal year,
subject only to the completed-import/current-dataset protections used by the API. The all-account overview does not
join the CDC Funding Profile mapping table to determine inclusion.

## Accounts

```http
GET /api/cdc-funding/v1/accounts?fiscal_year=2023
```

The `fiscal_year` query parameter is optional and defaults to the latest completed fiscal year. Pass
`scope=cdc_funding_profiles` to return only CDC Funding Profile-mapped account classifications:

```http
GET /api/cdc-funding/v1/accounts?fiscal_year=2023&scope=cdc_funding_profiles
```

Returns one row per federal account symbol. Account identity is the federal account symbol, not the account name. If a fiscal year unexpectedly contains multiple distinct nonblank names for the same symbol, the endpoint returns an internal error instead of choosing an arbitrary name.

Each account includes total, emergency, nonemergency, emergency share, and the four grant/contract breakdown fields. Missing combinations are returned as `"0.00"`. Accounts with exactly zero total obligations return `null` for `emergency_share`.

The account endpoint remains available for account-level analysis and backward compatibility. The standalone
`/cdc-funding` page uses this endpoint with `scope=all_accounts` for its detailed chart, table, search, expanded rows,
and CSV export. Detailed rows are grouped by federal account symbol, and each row displays the federal account name and
symbol.

## Categories

```http
GET /api/cdc-funding/v1/categories?fiscal_year=2023&scope=cdc_funding_profiles
```

The `fiscal_year` query parameter is optional and defaults to the latest completed mapped fiscal year. The categories
endpoint supports only `scope=cdc_funding_profiles`; `scope=all_accounts` returns a validation error because unmapped
annual rows do not have CDC Funding Profile category labels.

Returns one row per CDC Funding Profile budget category. A category may aggregate one or more mapped federal account
classification combinations. Mapping still uses the exact composite key:

```text
fiscal_year + federal_account_symbol + grant_or_contract + emergency
```

The endpoint joins annual account-summary rows to a distinct mapped-key/category relation so duplicate identical
mapping rows do not multiply obligations. Before aggregation, it validates that each exact mapped key resolves to no
more than one nonblank CDC Funding Profile category. Conflicts or blank mapped category labels return the internal
data-integrity error.

Each category includes total, emergency, nonemergency, grant, contract, emergency share, and the four
emergency/nonemergency by grant/contract breakdown fields. Category totals reconcile to the mapped overview totals
before a successful response is returned.

The categories endpoint remains available for future CDC Funding Profile analysis, but the standalone `/cdc-funding`
page does not use it.

The database schema, stored data, and ingestion process are unchanged. No migration, replacement summary table,
materialized view, source CSV request-time read, or USAspending request-time call is part of this page behavior.

## Error Behavior

Malformed query parameters use FastAPI validation responses, normally HTTP `422`.

Unavailable fiscal years return HTTP `404`:

```json
{
  "detail": {
    "code": "cdc_funding_fiscal_year_not_found",
    "message": "CDC funding data are not available for fiscal year 2022."
  }
}
```

If no fiscal years are available and no `fiscal_year` is provided, the API returns HTTP `404` with `cdc_funding_no_fiscal_years_available`.

Internal reconciliation failures return HTTP `500` with `cdc_funding_internal_reconciliation_error`.

## Current Scope

This API version is annual only. Monthly, quarterly, geography, recipient, and award-level drilldowns are outside v1.
The standalone overview page is separate from the geographic CDC Funding Map.
