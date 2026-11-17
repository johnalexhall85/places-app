# Historical periods for the area maps and the MCP server: plan

Approved by John on 2026-11-17. Claude is the project manager, as in the [MCP plan](../mcp/PLAN.md). Sources are in [SOURCES.md](SOURCES.md); per-agent progress is in [status/](status/).

## Decisions with John (2026-11-17)

| Question | Decision |
|---|---|
| Depth | Current period plus up to five earlier periods per measure, where the publisher still offers them |
| Comparability | Show every year. The legend carries that year's boundary or method note; years a measure doesn't publish are greyed out; older years draw on their own boundaries |
| MCP | Optional `period` on `get_area_values` and `get_measure_across_areas`, plus a new `get_measure_over_time`. No composite or change scores |
| Legend | Classes per year; the legend says colours are not comparable across years |
| Profiles | County, state, and district profiles do not change |
| Autonomy | As for MCP: gates only. Gate A is John's tryout on staging; Gate B is promotion to live |

## Design

- **History store, separate from current data.** It holds:
  - `area_pilot.observation_history`, primary key `(release_id, level, geoid, measure_id, observation_period)`, with an immutability trigger once published.
  - One history release and one pointer per product, under `dataset_id = '<current dataset_id>:history'`.
  - The same release, run, source_file, validation, review, and digest-gated `approve-publish` as current products.

  Current pointers, registries, observation tables, and the lookup functions the profiles use are unchanged.
- **History registries:** `backend/app/area_pilot/registry/history/<product>.json`. Each one lists, per measure and period: source locator, definition, population, boundary vintage, and note.
- **Boundaries:** `county_boundary_2020` and `tract_boundary_2010`. The map joins on `(level, boundary_vintage)`.
- **Read layer** (`lookup.py`): `measure_periods`, `area_values_at`, `measure_values_within(..., period=None)`, and `area_measure_series`. Also fix `national_reference` and `brfss_medians` to filter by period.
- **Map API:** the catalog gains `periods[]` per measure. `/map`, `/legend`, and `/table` send a non-current period to `history_api.py`.

## Ownership (see AGENTS.md, "Historical periods")

- **Claude:**
  - H0 sources and downloads
  - H1 migration, boundaries, history registry, CLI, and store
  - H3 lookup, catalog, and map API
  - Contract Amendment 2
  - All ingests and publication
  - Review, commits, and deploys
- **Antigravity:** H2 per-product parsers (offline, from files Claude archived) and H6 MCP evaluation updates.
- **Codex:** H4 year dropdown on `/area/*` and H5 MCP tools.

## Packages

| Pkg | Owner | Depends on |
|---|---|---|
| H0 sources, docs, downloads | Claude | – |
| H1 storage, boundaries, history CLI, parser interface | Claude | H0 |
| H2a–i parsers: CMS GV, USDA FEA, BRFSS, EPA AQI, AHRF, ACS B19013, ACS community, PLACES, CLH | Antigravity | H1 interface |
| H2 review, real ingest, staging publish | Claude | each H2 |
| H3 read layer and map API | Claude | H1 |
| H4 year dropdown | Codex | H3 catalog shape |
| H5 MCP tools | Codex | H3, Amendment 2 |
| H6 MCP eval | Antigravity | Amendment 2 |
| H7 staging walkthrough, Gate A, runbook, Gate B | Claude | all |

## Verification

- Profile snapshots in `docs/beta/contract-examples` stay byte-identical, and current pointers are unchanged.
- Spot values match each publisher for 5 areas per product-year.
- Old Connecticut counties draw for older years.
- Signed-in browser walk of all nine maps × years at 1365 and 375 px.
- MCP eval passes, including the history questions.
