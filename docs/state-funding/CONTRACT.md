# State funding contract, v1 (2026-11-19)

Owner: Claude. Codex implements §2–§4, and Antigravity audits against §5. Any change needs a dated amendment here, written by Claude.

Method version: `state-funding-v1`.

## 1. Read model (migration `e4b8c2f6a9d1`)

Schema `state_funding`. Each build writes new rows under a new `build_id`, then flips `active_build` in one transaction. The build keeps the two newest complete builds and deletes older ones. It refuses any database except `places_staging` unless it gets `--allow-live`, the same guard as `app.funding_report.build`.

| Table | Grain | Written by |
|---|---|---|
| `nofo_title` | `fon_key` × `source` | Claude's title loader. The build only reads it. |
| `build_run`, `active_build` | build | builder |
| `award` | build × `award_unique_key` | builder |
| `obligation` | build × `fiscal_year` × `state` × `award_unique_key` × `federal_account_symbol` × `is_supplemental` | builder |

### 1.1 `obligation`

The source is `cdc_funding.cdc_funding_awards` for fiscal years 2021–2026.

| Column | Source |
|---|---|
| `fiscal_year` | `fiscal_year` |
| `state` | `upper(trim(recipient_state))`. A blank value becomes `'__'` (Unattributed). Every code the source has is kept, including territories. |
| `award_unique_key` | `award_unique_key` |
| `federal_account_symbol` | `federal_account_symbol` |
| `federal_account_name` | The most frequent `federal_account_name` for that symbol in that fiscal year, with ties broken alphabetically. |
| `is_supplemental` | `emergency = 'Emergency'` |
| `amount` | `sum(transaction_obligated_amount)`. Rows that sum to exactly 0 are kept. |

Invariants:
- The sum of `amount` over all states, including `'__'`, for a fiscal year equals `sum(transaction_obligated_amount)` in `cdc_funding_awards` for that year. Each award-type and supplemental split matches the same way.
- No row is invented, allocated, or rescaled.

### 1.2 `award`

There is one row for every `award_unique_key` that appears in `obligation`.

| Column | Rule |
|---|---|
| `award_id` | `award_id_fain`, else `award_id_piid`, else `award_unique_key` |
| `award_type` | `'grant'` when `grant_or_contract = 'Grant'`, else `'contract'`. If an award has both, use the value on its row with the largest absolute amount. |
| `recipient_name`, `recipient_uei` | From File C, the latest `submission_period` row with a non-empty value. |
| `is_state_government` | **Grants:** true when any assistance prime transaction for the award has `business_types_description` containing `STATE GOVERNMENT` (case-insensitive), false when prime rows exist without it, and null when there is no prime row. **Contracts:** taken the same way from the contracts prime transactions' state-government business-type field. Record the column used in `build_run.sources`. |
| `fon` | The `funding_opportunity_number` from the assistance prime transactions for the award (the most frequent non-empty value), else TAGGS `fon` for the FAIN (`taggs.raw_awards.award_number`). Contracts have none. |
| `fon_key` | `app.funding_report.keys.nofo_key(fon)` |
| `project_title` | The TAGGS `award_title` for the FAIN: the most frequent non-empty value, as `fr_taggs_title` in `app/funding_report/build.py` does |
| `description` | `prime_award_base_transaction_description` from File C, the longest non-empty value |
| `cfda_number`, `cfda_title` | From File C, the row with the largest absolute amount |
| `usaspending_url` | `usaspending_permalink` from File C (always present in FY2025) |
| `search_text` | Lower-cased concatenation of `grant_name`, `project_title`, `description`, `recipient_name`, `award_id`, `fon`, and `cfda_number` |

`grant_name` and `name_source` take the first rule that gives a non-empty value:

1. `nofo_title.title` where `fon_key` matches and `source = 'grants_gov'`, giving `grants_gov_nofo_title`
2. `nofo_title.title` where `fon_key` matches and `source = 'cdc_funding_profiles'`, giving `cdc_funding_profiles_nofo_title`
3. `project_title`, giving `taggs_award_title`
4. `cfda_title`, giving `assistance_listing_title`
5. `description` cut to 200 characters at a word boundary, giving `award_description`. If even that is empty, use `award_id`.

`build_run.sources` records:
- the File C import run and its latest submission period per fiscal year;
- the TAGGS ingestion run;
- the prime-transaction source files;
- the `nofo_title` row counts by source.

`build_run.counts` records:
- rows per table;
- the dollars in `'__'` per fiscal year;
- the counts of each `name_source`.

## 2. Lookup (`app.state_funding.lookup`)

These are pure read functions over the active build, so the API and a future MCP tool share them. Filters are `fiscal_year`, `funding_type` (`all|regular|supplemental`), `award_type` (`all|grant|contract`), `account` (a symbol or None), and `recipient_type` (`all|state_government`). `recipient_type=state_government` keeps only awards where `is_state_government IS TRUE`.

Every function applies the filters to `obligation` joined to `award`, so the summary, the account list, and the grant list always add up to the same total.

## 3. HTTP API

The backend router prefix is `/state-funding/v1`. The public path is `/api/state-funding/v1/...` (the generic Nginx `/api/` block strips `/api`), and the demo-access gate applies. The state `code` is a two-letter postal code, case-insensitive. An unknown code, or one with no rows in any year, returns 404. `'__'` is never accepted.

Common query parameters: `fy` (default: the latest fiscal year in the build), `funding_type`, `award_type`, `account`, and `recipient_type`. A bad value returns 422.

### `GET /fiscal-years`
```jsonc
{ "fiscal_years": [2026, 2025, 2024, 2023, 2022, 2021], "default": 2026,
  "periods": { "2026": "FY2026 P12" },          // latest File C submission period per FY
  "build": { "build_id": 3, "finished_at": "…", "method_version": "state-funding-v1" } }
```

### `GET /states/{code}/summary`
```jsonc
{ "state": { "code": "CA", "name": "California" },
  "fiscal_year": 2026, "period": "FY2026 P12",
  "filters": { "funding_type": "all", "award_type": "all", "account": null, "recipient_type": "all" },
  "totals": { "total": 0.0, "regular": 0.0, "supplemental": 0.0, "award_count": 0, "recipient_count": 0 },
  "by_account": [ { "symbol": "075-0950", "name": "…", "regular": 0.0, "supplemental": 0.0, "total": 0.0, "award_count": 0 } ],
  "accounts_available": [ { "symbol": "075-0950", "name": "…" } ],   // accounts with rows for this state and FY, ignoring the account filter (for the selector)
  "citation": "Source: USAspending · Award financial (File C), CDC · FY2026 P12 · CHIP build 3",
  "notes": [ "…" ] }
```
- `by_account` is sorted by `abs(total)` descending.
- Amounts are JSON numbers rounded to cents.
- `award_count` counts awards with any row under the filters.
- `recipient_count` counts distinct `coalesce(recipient_uei, recipient_name)`.
- `notes` holds a fixed sentence when `totals.supplemental < 0`: "Supplemental amounts are negative when earlier emergency (for example COVID-19) obligations were reduced in this year."

### `GET /states/{code}/grants`
Extra parameters:
- `q`: case-insensitive substring match on `search_text`; every whitespace-separated term must match.
- `sort`: `amount|name|recipient`, default `amount`. Sorting by `amount` uses `abs(total)`.
- `dir`: `asc|desc`, default `desc`.
- `page` (starts at 1) and `page_size` (25, 50, or 100; default 25).

```jsonc
{ "fiscal_year": 2026, "filters": { … , "q": "" }, "page": 1, "page_size": 25, "total_rows": 0,
  "rows": [ { "award_unique_key": "ASST_NON_…", "award_id": "NU90TP922000",
              "award_type": "grant", "grant_name": "…", "name_source": "grants_gov_nofo_title",
              "project_title": "…", "description": "…", "recipient_name": "…", "recipient_uei": "…",
              "is_state_government": true, "fon": "CDC-RFA-TP-24-0001", "cfda_number": "93.069", "cfda_title": "…",
              "accounts": [ { "symbol": "075-0956", "name": "…", "regular": 0.0, "supplemental": 0.0 } ],
              "regular": 0.0, "supplemental": 0.0, "total": 0.0, "usaspending_url": "https://…" } ],
  "sum_total": 0.0,      // over every row matching the filters and q, not just this page
  "citation": "…" }
```

### `GET /states/{code}/grants.csv`
Uses the same filters and `q` as the grants list, returns every row, and is sorted like the list. The columns are the row fields, with `accounts` flattened as `symbol name` joined by `; `. The first line is the citation, prefixed with `# `. The filename is `chip-cdc-funding-{code}-FY{fy}.csv`.

## 4. Page (`/cdc-funding/state/{code}`)

This section was set in PLAN.md and the decisions with John.
- Brand: [EXECUTION_PLAN.md §Brand](../beta/EXECUTION_PLAN.md) and `frontend/src/community/tokens.css`. Regular amounts use Brand Blue `#0277BD`, and supplemental amounts use Peach `#F0B97D`. Negative bars extend left of a zero line.
- No time-series chart.
- Every amount shows its sign. A source line sits under the chart and under the table.
- `name_source` appears as a small label, such as "NOFO title (Grants.gov)", "Project title (TAGGS)", "Assistance listing", or "Award description".
- Each grant row carries `id="award-{award_unique_key}"` and `data-award-key` so the future grant-history page can attach to it.
- The query string keeps `fy`, the filters, `q`, `sort`, and `page` so views can be shared. Unknown parameters, including the old `mode` and `metric`, are ignored.

## 5. Audit invariants (Antigravity's `test_state_funding_audit.py`)

For every fiscal year, and for every `funding_type × award_type` combination:
1. The sum of `obligation.amount` over all states, including `'__'`, equals the matching `cdc_funding_awards` sum, within $0.01.
2. For FY2023–FY2026, with `funding_type × award_type` equal to (all × all), the national total equals what `/api/cdc-funding/v1` reports for that year (scope `all_accounts`).

For 10 sampled states × every fiscal year:
3. `summary.totals.total` equals the sum of `by_account.total`, which equals `grants.sum_total`.
4. In each grant row, `regular + supplemental = total`, and the account amounts sum to the row.

Across the whole build:
5. Every `award` row has a non-empty `grant_name` and a valid `name_source`.
6. No `award` row is orphaned or missing relative to `obligation`.
