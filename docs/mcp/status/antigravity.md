# Antigravity status: CHIP MCP server

Updated by Antigravity at the end of each task. Claude reads this file before reviewing.

| Package | State | Branch | Notes |
|---|---|---|---|
| M3 Independent evaluation suite | Done (offline validation & unit tests passing; ready for Claude `--expected-only` & M4 live run) | `agy/mcp-m3` | 42 questions (32 regular + 10 traps), 59 expected tool calls across all 7 tools, 8 public area products + 3 facility blocks, and all 4 geographic levels (`state`, `county`, `tract`, `cd`). `test_checks.py` (7 unit tests) and `run_eval.py --validate` pass. |

## How Claude should run `--expected-only` and the full eval

From `/home/john/chip-agy` (or after merging `agy/mcp-m3` into `beta`):

1. **Validate `questions.yaml` offline (no DB or server):**
   ```bash
   cd /home/john/chip-agy/backend
   PYTHONPATH=. .venv-mcp/bin/python tests/mcp_eval/run_eval.py --validate
   ```
2. **Run pure check unit tests:**
   ```bash
   cd /home/john/chip-agy/backend
   PYTHONPATH=. .venv-mcp/bin/python -m pytest tests/mcp_eval/test_checks.py -v
   ```
3. **Compute and verify expected values against `places_staging` without a server (`--expected-only`):**
   ```bash
   cd /home/john/chip-agy/backend
   PYTHONPATH=. .venv-mcp/bin/python tests/mcp_eval/run_eval.py --expected-only --report ../deliverables/mcp/eval_report.md
   ```
4. **Run the full evaluation against the live MCP server in M4:**
   ```bash
   cd /home/john/chip-agy/backend
   PYTHONPATH=. .venv-mcp/bin/python tests/mcp_eval/run_eval.py --url http://127.0.0.1:8011/mcp --report ../deliverables/mcp/eval_report.md
   ```

## Coverage counts (`backend/tests/mcp_eval/questions.yaml`)

- **Total questions:** 42 (32 standard + 10 trap questions)
- **Total tool calls:** 59
  - `get_area_values`: 19
  - `get_measure_across_areas`: 16
  - `find_places`: 10
  - `get_area_context`: 6
  - `search_measures`: 4
  - `get_measure_details`: 2
  - `list_data_sources`: 2
- **Questions by product / facility block:**
  - `places`: 18, `acs_profile`: 14, `acs`: 8, `clh`: 8, `cms_gv`: 8, `usda_fea`: 7, `brfss`: 6, `epa_aqi`: 6
  - Facility blocks: `health_centers`: 6, `nursing_homes`: 6, `tri_facilities`: 6
  - Excluded product (`ahrf` trap): 1
- **Levels covered:** `county` (49), `tract` (19), `state` (16), `cd` (13)
- **Showcase & required geographies:** Person County NC (`37145`), Kanawha County WV (`54039`), Fresno County CA (`06019`), WV-01 (`5401`), Alabama (`01`), Texas (`48`, 254 counties), Los Angeles County (`06037`, 2,498 tracts).
- **Trap questions (10):**
  1. `Q33` (`ahrf_excluded`): `search_measures` and `get_area_values` for `ahrf:phys_nf_prim_care_pc_exc_rsdt_23`.
  2. `Q34` (`time_trend_one_period`): multi-year trend request on `places:diabetes_crudeprev` in `54039`.
  3. `Q35` (`no_composite_score`): healthiest-county composite score request in Alabama (`01`).
  4. `Q36` (`epa_aqi_no_monitor`): `epa_aqi:median_aqi` in unmonitored county (`01001`) and across Alabama (`01`, 15 available / 52 `no_reported_value`).
  5. `Q37` (`kentucky_brfss_not_published`): Kentucky (`21`) 2023 `brfss:diabetes` (`not_published`) vs 2022 `brfss:dental_visit` (`available`), plus all-states `brfss:diabetes` (`21` and `42` in `without_value`).
  6. `Q38` (`cms_not_published_for_cd`): `cms_gv:std_payment_per_capita` requested at `level="cd"` for WV (`54` / `5401`).
  7. `Q39` (`tracts_require_county`): `get_measure_across_areas` at `level="tract"` with omitted `within` and with 2-digit state GEOID `within="37"`.
  8. `Q40` (`medicare_original_beneficiaries`): `cms_gv` measures in `37145` and `54039` checked for `"Original Medicare beneficiaries"` population label and general interpretation rule.
  9. `Q41` (`ct_pr_coverage_status`): Connecticut planning region `09110` (`boundary_not_comparable` in `usda_fea`) and Puerto Rico `72001` (`not_covered` in `usda_fea`, `not_published` in `cms_gv`).
  10. `Q42` (`limits_and_truncation`): 12 counties × 41 measures (492 rows > 400-row cap) error check in `get_area_values`, and 2,498 tracts in `06037` size-cap / truncation check in `get_measure_across_areas` verifying all 58 `without_value` rows are preserved.

## Contract ambiguities found in `docs/mcp/TOOL_CONTRACT.md`

1. **Section "Public product allowlist" & M3 Global Checks vs Section 7 (`list_data_sources`) — `"ahrf"` string presence:**
   - Section "Public product allowlist" states: *"`ahrf` is excluded ... It never appears in any output, including search results, topics, and catalogs."* M3's global check states: *"No `ahrf` anywhere in the serialized output."*
   - However, Section 7 (`list_data_sources`) explicitly requires returning `"excluded": [{"product": "ahrf", "reason": "Pending the source agency's answer on redistribution; available on the CHIP website."}]`.
   - **How `run_eval.py` handles this:** `check_no_ahrf` rejects any occurrence of `"ahrf"` anywhere in the serialized JSON for all tools, and for `list_data_sources` specifically strips `data.excluded` before scanning while verifying `data.excluded` contains the required `"ahrf"` entry.

2. **Section "Value row" vs Section 5 (`get_measure_across_areas`) — `"position"` key on value rows:**
   - Section "Value row" says *"shared by `get_area_values`, `get_measure_across_areas` — Built from one `lookup` row. Keep these keys and add nothing else"* (listing 17 keys without `position`), whereas Section 5 says each row in `with_value` *"also carries `"position"`, using competition numbering where equal values share a position (1, 2, 2, 4)."*
   - Furthermore, if the server shares a single Pydantic `ValueRow` model across both tools with `position: int | None = None`, `position: null` could appear on `get_area_values` or `without_value` rows unless `exclude_none=True` is used.
   - **How `run_eval.py` handles this:** `check_value_row_shape` allows `"position"` on `get_measure_across_areas` rows and allows `"position": None` on `get_area_values` rows while rejecting any other extra keys.

3. **Section 5 (`get_measure_across_areas`) — `position` numbering when `sort="geoid"`:**
   - Section 5 defines `sort` as `geoid` (default), `value_desc`, or `value_asc`, and states that each row in `with_value` carries `"position"` with competition numbering `(1, 2, 2, 4)`. When `sort="geoid"`, equal values are not necessarily adjacent, so it is ambiguous whether `position` under `sort="geoid"` is sequential `1..N` (sharing a position only on adjacent ties) or computed from value rank.
   - **How `run_eval.py` handles this:** `check_competition_positions` enforces strict adjacent competition numbering `(1, 2, 2, 4)` on `value_desc` and `value_asc`, and accepts either GEOID-order or value-rank competition numbering when `sort="geoid"`.

4. **Section 4 (`get_area_values`) vs Section "Errors" — requesting a measure at a level it does not publish:**
   - Section 4 says: *"Unpublished measures: a measure not published at `level` is skipped and named in a warning, which lists the levels where it is published."*
   - Section "Errors" says: *"Bad input raises `mcp.server.mcpserver.exceptions.ToolError` (... a level the measure doesn't publish)."*
   - When `get_area_values` is called with a mix of published and unpublished measures for `level` (or only unpublished measures), it is ambiguous whether the server raises `ToolError` or skips the unpublished measure with a warning.
   - **How `run_eval.py` handles this:** In `Q38`, Call 0 tests `get_measure_across_areas` (which unambiguously raises `ToolError` via `lookup.measure_values_within`), and Call 1 tests `get_area_values` with `expect_unpublished_level_handled`, accepting either `ToolError` naming `state`/`county` or a response that skips `cms_gv` and names `state` and `county` in `warnings`.

5. **Section "Response envelope" — `sources` for non-value tools (`find_places`, `search_measures`, `get_measure_details`, `get_area_context`, `list_data_sources`):**
   - Section "Response envelope" says: *"`sources`: only the products whose rows appear in `data`."* For tools that do not return measure value rows (e.g., `get_area_context`, which returns facility blocks that already embed their own `release` objects, or `get_measure_details`), it is not specified whether top-level `sources` is `[]` or lists the queried products.
   - **How `run_eval.py` handles this:** Strict `sources == data products` equality is enforced on `get_area_values` and `get_measure_across_areas`.

6. **Section 2 (`search_measures`) — `"health-care-resources"` topic and `measures` when called with no arguments:**
   - In `backend/app/community/topics.json`, all 5 `measure_keys` under `"health-care-resources"` belong to `ahrf`. Since `ahrf` is excluded from topics and catalogs, it is ambiguous whether `"health-care-resources"` is omitted from `search_measures()` topics or returned with `measure_count: 0`. Also, Section 2 says `"No arguments: returns the topic list"` while the `data` schema shows `{"measures": [...], "topics": [...only when no query]}`—leaving open whether `measures` is `[]` or populated when `query` is omitted.

7. **Section 3 (`get_measure_details`) — `measure_key` vs `product` + `measure_id`:**
   - `lookup.catalog()["measures"]` uses `"product"` and `"measure_id"`, whereas MCP tools use `"measure_key": "<product>:<measure_id>"`. Section 3 does not state whether `get_measure_details` items carry `"measure_key"`, `"product"` + `"measure_id"`, or both.
   - **How `run_eval.py` handles this:** `verify_call_against_lookup_and_checks` accepts either `m["measure_key"]` or `f"{m['product']}:{m['measure_id']}"`.

## Diary facts (2026-11-17T15:08:00Z)

- **Task:** M3 independent evaluation suite for the CHIP MCP server on branch `agy/mcp-m3` in `/home/john/chip-agy`.
- **Created files:**
  - `backend/tests/mcp_eval/__init__.py`
  - `backend/tests/mcp_eval/questions.yaml` (42 questions: 32 regular + 10 traps; 59 tool calls)
  - `backend/tests/mcp_eval/run_eval.py` (deterministic runner supporting `--validate`, `--expected-only`, `--url`, and `--report`)
  - `backend/tests/mcp_eval/test_checks.py` (7 offline pytest unit tests for pure check functions and YAML validation)
  - `deliverables/mcp/eval_report.md` (initial offline validation report; overwritten on `--expected-only` / `--url` runs)
- **Verification run in sandbox:**
  - `backend/.venv-mcp/bin/python -m py_compile backend/tests/mcp_eval/run_eval.py backend/tests/mcp_eval/test_checks.py` -> exit 0.
  - `cd backend && PYTHONPATH=. .venv-mcp/bin/python tests/mcp_eval/run_eval.py --validate --report ../deliverables/mcp/eval_report.md` -> Validation PASSED (42 questions, 10 traps, all 7 tools, 8 public products + 3 facility blocks, 4 levels, and all showcase places covered).
  - `cd backend && PYTHONPATH=. .venv-mcp/bin/python -m pytest tests/mcp_eval/test_checks.py -v` -> 7 passed in 0.58s.
- **Next action:** Claude runs `--expected-only` and `--url http://127.0.0.1:8011/mcp` outside the sandbox in M4, then reviews and commits `agy/mcp-m3`.
