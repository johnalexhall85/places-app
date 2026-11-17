# CHIP MCP server: tool contract

Owner: Claude (project manager). Codex builds to this contract (M2) and Antigravity tests against it (M3). Change it only through Claude; record any needed change in your status file.

## Server

- **Package:** `backend/app/mcp_server/`. ASGI app `app.mcp_server.app:app`, served by uvicorn.
- **SDK:** official `mcp==2.3.0`. In 2.x the class is `from mcp.server import MCPServer` (there is no `FastMCP`). Build the app with `mcp.streamable_http_app(streamable_http_path="/mcp", json_response=True, stateless_http=True, transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...]))`. `TransportSecuritySettings` is in `mcp.server.transport_security`.
- **Separate venv.** `mcp` 2.3 needs Starlette ≥0.48 and uvicorn ≥0.31, which conflict with the website's FastAPI 0.115 pin, so the MCP server runs from `backend/.venv-mcp`, built from `backend/app/mcp_server/requirements.txt`. That file pins at least `mcp==2.3.0`, a current `fastapi`, `SQLAlchemy==2.0.34`, `psycopg[binary]==3.2.3`, `python-dotenv==1.0.1`, `requests`, `openpyxl`, `pypdf`, and `uvicorn`. These are the modules that importing `app.area_pilot.lookup` and `app.routers.search` pulls in, verified 2026-11-17. Never add `mcp` to `backend/requirements.txt`.
- **Allowed hosts** come from the environment variable `CHIP_MCP_ALLOWED_HOSTS` (comma-separated). The default is `127.0.0.1:*,localhost:*`. Staging adds `chip-beta.publicdataobservatory.org`; production adds `mcp.publicdataobservatory.org`.
- **Database:** `app.db.SessionLocal` (follows `DATABASE_URL`). In deployment that URL uses the read-only role `chip_mcp_ro`. Open one session per tool call and always close it.
- **Data access:** only `app.area_pilot.lookup`, `app.routers.search.search_counties` (called with explicit `q`, `limit`, `db` arguments), and `app/community/topics.json`. Never write SQL in `mcp_server`.
- **Server name** `CHIP Public Health Data`. Pass `instructions` (shown to the model) with the workflow and rules in the "Server instructions" section below. A `GET /healthz` custom route returns `{"ok": true}`.
- **Tool annotations** on every tool: `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`, `openWorldHint: false`.
- **Typed returns.** Every tool returns a Pydantic model (or TypedDict) so clients receive `structured_content` and an output schema. A plain `dict` return produces text only (verified in the M0 spike).

## Public product allowlist

Public products: `places`, `acs`, `acs_profile`, `brfss`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea` (all `lookup.SPECS` keys except `ahrf`), plus the facility blocks `health_centers`, `nursing_homes`, and `tri_facilities` from `lookup.area_facilities`.

**`ahrf` is excluded** because HRSA's answer on redistribution is pending. It never appears in any output, including search results, topics, and catalogs. A request naming an `ahrf:` key returns an error saying it is not available through the public server. Keep the allowlist in one constant in `config.py`.

## Identifiers

- **Measure key:** `"<product>:<measure_id>"`, for example `places:diabetes_crudeprev`, `acs:B19013_001E`, `acs_profile:total_population`, `brfss:diabetes`, `epa_aqi:median_aqi`.
- **Levels:** `state` (2-digit FIPS), `county` (5-digit), `tract` (11-digit), and `cd` (4-digit: state FIPS plus district, 119th Congress; for example `5401` = West Virginia 1st).

## Response envelope (every tool)

```json
{
  "data": { "...": "tool-specific, below" },
  "sources": [
    {"dataset_id": "cdc_places_county_2025_pilot", "product": "places",
     "product_name": "PLACES 2025 county and tract pilot",
     "publisher": "Centers for Disease Control and Prevention",
     "release_id": "7bf96574-ac68-4d2f-9db8-95b07fbbf622", "source_release_id": "2025-12-12",
     "published_at": "2026-11-15T01:01:07.000510+00:00", "landing_page": "https://data.cdc.gov/..."}
  ],
  "interpretation_rules": ["..."],
  "warnings": ["..."]
}
```

- **`sources`:** only the products whose rows appear in `data`. This is not every active release: `lookup.area_values()["releases"]` lists every product it visited, so filter it.
- **`interpretation_rules`:** the general rules below, plus `limitations` from `lookup.catalog()["products"]` for each product in `sources`.
- **`warnings`:** truncation, excluded products, unknown keys, and the ordering caveat for sorted lists. Use an empty list when there are none.

**General interpretation rules** (verbatim strings, all in `config.py`):

1. Values are published by the named source for exactly the area shown; CHIP never adds, averages, or derives values across areas.
2. A missing, suppressed, or not-published value is not zero; read `status_text`.
3. Each value has its own period, population, and source; do not treat different periods or populations as directly comparable without saying so.
4. Medicare (cms_gv) measures describe Original Medicare beneficiaries, not all residents.
5. TRI facilities are facilities that report to EPA's Toxics Release Inventory; reporting does not mean a release, a violation, or a health risk.
6. Each measure has one published period in CHIP; there is no time series.

## Value row (shared by `get_area_values`, `get_measure_across_areas`)

Built from one `lookup` row. Keep these keys and add nothing else:

```json
{
  "measure_key": "places:diabetes_crudeprev",
  "label": "Diagnosed diabetes",
  "area": {"level": "county", "geoid": "37145", "name": "Person"},
  "value": 14.9,
  "unit": "percent",
  "storage_scale": null,
  "status": "available",
  "status_text": "Published value",
  "uncertainty": {"kind": "ci95", "low": 12.7, "high": 17.2, "label": "95% confidence interval"},
  "period": "2023",
  "population": "adults",
  "value_type": "crude_prevalence",
  "boundary_vintage": "TIGER/Line 2023 county",
  "release_id": "7bf96574-ac68-4d2f-9db8-95b07fbbf622",
  "notes": {},
  "source_credit": null,
  "citation": "Source: Centers for Disease Control and Prevention · PLACES 2025 county and tract pilot · 2023 · release 2025-12-12"
}
```

The values above are real: they are `lookup.area_values(db, "county", ["37145"], measure_ids=["diabetes_crudeprev"])` on `places_staging`, 2026-11-17.

- **Citation format:** `"Source: {publisher} · {product_name} · {period} · release {source_release_id}"`.
- **`area.name`:** from `lookup.area_info` (or the `name` field of `measure_values_within`). Null when no current boundary carries the area.
- **`uncertainty`:** pass through exactly; the kinds `ci95`, `moe90`, and `none` stay distinct.
- **`storage_scale`:** pass through. For example, the CMS readmission rate is stored as a 0–1 value.

## Tools

### 1. `find_places(query: str, levels: list[str] | None = None, limit: int = 10)`

Use it to turn a place name into a GEOID before any data call.

- **Matching:**
  - States by name, postal abbreviation, or FIPS (`lookup.states`).
  - Counties through `search_counties` (names such as "Person County, NC", "Kanawha", "fips:37145").
  - Districts through patterns such as `WV-1`, `WV-01`, `West Virginia 1st`, `NC district 4`, and `AK at-large`, using `lookup.state_districts`.
- **`levels`** filters to a subset of `state`, `county`, and `cd`. `limit` is between 1 and 25.
- **`data`:** `{"matches": [{"level", "geoid", "name", "state_name", "display_name"}]}`, with `display_name` like `"Person County, North Carolina"` or `"West Virginia 1st congressional district (119th Congress)"`.
- **No match:** an empty list plus a warning suggesting a FIPS code.

### 2. `search_measures(query: str | None = None, topic: str | None = None, level: str | None = None, limit: int = 25)`

- **No arguments:** returns the topic list (`slug`, `title`, `summary`, measure count) so the model can browse.
- **Otherwise:** case-insensitive token matching over label, definition, measure_id, product name, category, and topic titles, with a small synonym map (for example `poverty`, `income`, `uninsured`/`insurance`/`coverage`, `air`/`aqi`, `food`/`snap`/`grocery`, `medicare`, `diabetes`, `blood pressure`/`hypertension`, `smoking`/`tobacco`, `obesity`, `mental`/`depression`). `topic` restricts to that topic's `measure_keys`, and `level` restricts to measures published at that level.
- **`data`:** `{"measures": [{"measure_key", "label", "product_name", "publisher", "unit", "period", "population", "levels", "topics"}], "topics": [...only when no query]}`, at most `limit` (≤50).

### 3. `get_measure_details(measure_keys: list[str])`

Up to 20 keys. Returns the full `lookup.catalog` measure metadata for each: definition, denominator, interpretation, unit, storage_scale, kind, period, population, value_type, levels, uncertainty_kind, landing_page, underlying_source, source_credit, paired_measure (as a key), topics, the product's limitations, and the active release.

- **Unknown key:** reported in `warnings`, not raised.
- **`data`:** `{"measures": [...]}`.

### 4. `get_area_values(level: str, geoids: list[str], measure_keys: list[str] | None = None, topic: str | None = None)`

Values for 1–25 areas at one level, for comparisons and profiles. Calls `lookup.area_values(db, level, geoids, products=..., measure_ids=...)`.

- **Measure selection:** `measure_keys` or `topic` selects the measures. With neither, every public measure published at that level is returned.
- **Row cap:** above 400 rows the call returns an error asking the model to narrow the measures or areas.
- **Unpublished measures:** a measure not published at `level` is skipped and named in a warning, which lists the levels where it is published.
- **`data`:** `{"level", "areas": [{"geoid", "name"}], "values": [value rows]}`.

### 5. `get_measure_across_areas(measure_key: str, level: str, within: str | None = None, sort: str = "geoid", limit: int = 25)`

One measure for every area inside a parent. Calls the new `lookup.measure_values_within(db, product, measure_id, level, parent_geoid)` (added in M1; see its docstring).

- **Levels and parents:** `level=state` takes no `within`. `county` and `cd` need a state GEOID or a state name or abbreviation, resolved through `find_places` logic. `tract` needs a county GEOID.
- **`sort`:** `geoid`, `value_desc`, or `value_asc`. `limit` is between 1 and 300, and applies to the sorted list with values.
- **`data`:**
  - `measure`: compact metadata.
  - `parent`: `{level, geoid, name}`.
  - `total_areas`: the count of all areas.
  - `with_value`: value rows that have a non-null value, sorted as asked. Each also carries `"position"`, using competition numbering where equal values share a position (1, 2, 2, 4).
  - `without_value`: **every** row with a null value, in GEOID order, never truncated (status and status_text tell why).
  - `truncated`: true when `with_value` was cut to `limit`.
- **Warnings:**
  - For value sorts, always add: `"Order is by point estimate. Where uncertainty ranges overlap, the difference may not be meaningful. This is a list of one published measure, not a ranking of overall health."`
  - If `truncated`, add `"Showing N of M areas with values."`
- **Never** use the words best, worst, top performer, or score in field names or warnings.

### 6. `get_area_context(level: str, geoid: str)`

Where an area sits and what is listed inside it. No measure values.

- **`area`:** `lookup.area_info` without geometry (name, state, county, bbox, point, boundary_vintage).
- **`related`:**
  - `state`: its counties (`lookup.state_counties`) and districts (`lookup.state_districts`).
  - `county`: overlapping districts (`lookup.county_districts`, with share fields and the note).
  - `cd`: overlapping counties (`lookup.district_counties`).
  - `tract`: its county.
- **`facilities`** (state, county, cd only): from `lookup.area_facilities`, per block `{name, count, published, release, method, limitations, examples}`. `examples` holds the first 10 rows (name, city, plus `program`/`site_type`, `provider_type`/`overall_rating`, or `sector_codes`); the row cap is 10, not 200.

### 7. `list_data_sources()`

- **`data`:**
  - `products`: the public allowlist from `lookup.catalog()["products"]` (name, publisher, levels, release, limitations, landing_page, measure_count).
  - `facility_products`: health centers, nursing homes, and TRI, with their releases.
  - `excluded`: `[{"product": "ahrf", "reason": "Pending the source agency's answer on redistribution; available on the CHIP website."}]`.
  - `status_glossary`: `lookup.STATUS_TEXT`.
  - `levels`.
  - `notes`: one period per measure, no time series, and boundary vintages.

## Errors

- **Bad input** raises `mcp.server.mcpserver.exceptions.ToolError` (unknown level, malformed GEOID, too many areas or keys, excluded product, a level the measure doesn't publish). The message must say what to do next, for example "Use find_places to look up the 5-digit county GEOID" or "This measure is published for county and tract; use one of those levels". Map `lookup.LookupError_` messages through unchanged.
- **Unexpected exceptions** are logged with a traceback and returned as `"Internal error; please retry or narrow the request"`. The text must not include SQL or stack details.

## Limits and runtime

- **Size:** if a serialized response is over 60,000 bytes, cut `with_value` or `values`, set `truncated`, and add a warning; `without_value` is never cut.
- **Cache:** in-process LRU (about 512 entries) keyed by tool name, normalized arguments, and a fingerprint of `lookup.active_releases(db)`, so a newly published release changes the key.
- **Logging:** one JSON line per call to stdout with ts, tool, arguments (truncated to 500 chars), duration_ms, row count, cached, and error class. No client IP or headers.

## Server instructions (MCP `instructions` text, keep under 1,200 characters)

> CHIP (Community Health Intelligence Platform, Public Data Observatory) serves published U.S. public-health and community data for states, counties, census tracts, and 119th Congress districts. Workflow: call find_places to get GEOIDs, search_measures to get measure keys, then get_area_values (compare up to 25 areas) or get_measure_across_areas (one measure for every county or district in a state, or tracts in a county). Use get_measure_details for definitions and get_area_context for related areas and listed facilities. Cite every number with its `citation`. Report status_text when a value is missing. Do not add, average, or rank values into composite scores, and say when periods or populations differ.

## Real examples to check against (staging, 2026-11-17)

| Call | Expected |
|---|---|
| `lookup.area_values(db,'county',['37145'],measure_ids=['diabetes_crudeprev'])` | value 14.9, ci95 12.7–17.2, period 2023, adults |
| `measure_values_within(db,'places','diabetes_crudeprev','county','01')` | 67 rows, all available, first 01001 Autauga 13.3 |
| `measure_values_within(db,'places','diabetes_crudeprev','county','48')` | 254 rows: 253 available, 1 `not_in_release` |
| `measure_values_within(db,'epa_aqi','median_aqi','county','01')` | 67 rows: 15 available, 52 `no_reported_value` |
| `measure_values_within(db,'brfss','diabetes','state')` | 56 rows: 54 available, 2 `not_published` (Kentucky, Pennsylvania) |
| `measure_values_within(db,'acs','B19013_001E','tract','06037')` | 2,498 rows (2,440 available, 42 missing, 16 open_ended), about 0.4 s |
