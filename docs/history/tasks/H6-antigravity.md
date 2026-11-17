# Task H6 (Antigravity): MCP evaluation for earlier periods

Assigned by Claude. Worktree `/home/john/chip-agy`, branch `agy/history-h2` (Claude fast-forwards it). Owned paths: `backend/tests/mcp_eval/**`, `deliverables/mcp/**`, and `docs/history/status/antigravity.md`. The rules are the same as M3: no network, no commits. Claude runs `--expected-only` and `--url` outside your sandbox.

## Read first

1. [docs/mcp/TOOL_CONTRACT.md](../../mcp/TOOL_CONTRACT.md), **Amendment 2**.
2. The lookup history functions at the end of `backend/app/area_pilot/lookup.py`. The evaluation computes expected values from them, as it already does from `area_values` and `measure_values_within`.
3. `backend/tests/mcp_eval/run_eval.py`, `questions.yaml`, and `test_checks.py`.

## Change

1. **Q34** (`time_trend_one_period`) becomes a regular question: "How has standardized Medicare spending per beneficiary in Person County, NC changed over the years?" The expected call is `get_measure_over_time(level='county', geoid='37145', measure_key='cms_gv:std_payment_per_capita')`. Checks:
   - `series` periods are ascending and unique, and each row has `period`, `note`, `release_id`, `boundary_vintage`, and `citation`.
   - Values match `lookup.area_measure_series`.
   - The fixed warning text from Amendment 2 item 5 is present.
   - No key named like `change`, `trend`, `difference`, or `pct_change` appears anywhere in `data`.
2. **Replace** `expect_single_period_per_measure` and the `list_data_sources` "one period" check with checks for the new rule 6 text and for per-product period lines.
3. **Add about 10 questions** (5 regular, 5 traps), with expected values from `lookup`:
   - `get_measure_across_areas('cms_gv:readmission_rate','county', within='09', period='2020')`: eight rows `09001`…`09015`, `boundary_vintage` naming 2020, and `note` in `data.measure`.
   - `get_area_values('county',['54039'],['cms_gv:er_visits_per_1000'], period='2021')`: one row with period `2021` and a citation containing `2021`.
   - `search_measures(query='diabetes')`: every item has a `periods` list whose first entry is the current period.
   - `get_measure_details(['cms_gv:std_payment_per_capita'])`: `periods` entries carry `note` and `available`.
   - `get_measure_over_time('county','09001','cms_gv:readmission_rate')`: the current period is not published for `09001` (planning regions since 2022), earlier periods have values, and a boundary-vintage warning is present.
   - **Trap:** `get_measure_across_areas('acs_profile:poverty_pct','cd', within='54', period='2015–2019')` raises the district `ToolError`.
   - **Trap:** `get_measure_over_time` for an AHRF key raises the withheld-AHRF `ToolError`.
   - **Trap:** `get_area_values(level='state', geoids=['54'], measure_keys=['brfss:diabetes'], period='1999')` skips with a warning listing published periods.
   - **Trap:** a user asks for "the percentage change from 2019 to 2023". The expected calls are plain value tools, and the check confirms the server returns values only, with no computed change.
   - **Trap:** `get_measure_across_areas(..., sort='value_desc', period='2020')` sorts within the one period only; `position` follows that period's values.
4. **Expected values must be dynamic** (computed from `lookup` at run time), because more history releases will be published on staging after this task. Never hard-code values that depend on what is published, except where a question is about CMS 2019–2023, which is published.
5. **`test_checks.py`:** unit tests for every new check function, using hand-written sample responses.

## Done when

- `--validate` and `test_checks.py` pass in your sandbox.
- The status row lists the new question IDs, the call counts, and the commands for Claude to run.

Finish with a report of five lines or fewer.
