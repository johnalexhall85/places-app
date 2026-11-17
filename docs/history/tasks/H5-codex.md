# Task H5 (Codex): MCP tools for earlier periods

Assigned by Claude, 2026-11-17. Worktree `/home/john/chip-codex`, branch `codex/history` (fast-forwarded to include H4 and the read layer). Owned paths: `backend/app/mcp_server/**`, `backend/tests/test_mcp_*`, and `docs/history/status/codex.md`. The rules are the same as M2: no commits, deploys, or sudo.

## Read first

1. [docs/mcp/TOOL_CONTRACT.md](../../mcp/TOOL_CONTRACT.md), including **Amendment 2** at the end, which this task implements.
2. The history functions at the end of `backend/app/area_pilot/lookup.py`:
   - `measure_periods`
   - `area_values_for_period`
   - `history_values_within` (through `measure_values_within(..., period=)`)
   - `area_measure_series`

   Read only through `lookup`, as before.
3. `backend/app/mcp_server/{tools,measures,config,envelope}.py` and the existing `test_mcp_*` tests.

## Build

Implement Amendment 2 items 1–8 exactly:
- the new rule 6 text
- `period` on `get_area_values` and `get_measure_across_areas`
- `note` on rows (in `data.measure` for compact rows)
- per-row citation and history `sources`
- the new `get_measure_over_time` tool
- `periods` in `search_measures` and `get_measure_details`
- the `list_data_sources` period lines

AHRF stays withheld for every period and every tool.

On staging only CMS GV has a published history release so far: release `89e8cb19-…`, 2019–2023. The other products have declared periods that `measure_periods` returns with `available: false`. The tools must handle both cases. Use these for integration checks against `places_staging`:
- `get_measure_over_time('county','37145','cms_gv:std_payment_per_capita')`: 2019 → 2024, six rows.
- `get_measure_across_areas('cms_gv:readmission_rate','county','09',period='2020')`: Connecticut's eight former counties, `09001`…`09015`.
- `get_area_values(level='state', geoids=['54'], measure_keys=['brfss:diabetes'], period='2021')`: skipped with a warning listing the published periods.

## Tests

- **Unit tests** in the existing style: the period parameter, the default being unchanged, the unpublished-period warning and error, the `cd` error, the series order, the boundary-vintage warning, AHRF raising, and the size cap on a long series.
- **Integration tests** following `test_mcp_integration.py` for the three calls above.

Run `PYTHONPATH=. .venv-mcp/bin/python -m pytest -q tests/test_mcp_*.py` from `backend/`. `.venv-mcp` is a symlink in your worktree; if it is missing, use `/home/john/chip-agy/backend/.venv-mcp`.

## Done when

1. All MCP tests pass, and the 44-question evaluation is not broken by default behaviour. Q34 and the one-period checks are expected to change; Antigravity updates them in H6. List exactly which checks you expect to fail and why.
2. `docs/history/status/codex.md` has an H5 row and diary facts.

Finish with a report of five lines or fewer.
