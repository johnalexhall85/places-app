# Antigravity status: CHIP MCP server

Updated by Antigravity at the end of each task. Claude reads this file before reviewing.

| Package | State | Branch | Notes |
|---|---|---|---|
| M3 Independent evaluation suite | Done | `agy/mcp-m3` | 42 questions (32 regular + 10 traps), 59 expected tool calls across all 7 tools. Ran outside sandbox by Claude: `--validate` pass, `test_checks.py` 7 pass, `--expected-only` 41/42, live server 40/42 (p50 50.9 ms, p95 126.2 ms). |
| M3b Align evaluation with Amendment 1 | Done (`--validate` & `test_checks.py` 8/8 passing) | `agy/mcp-m3` | Updated `run_eval.py`, `questions.yaml` (now 44 questions: 32 regular + 12 traps, 65 tool calls), and `test_checks.py` (8 unit tests) to Amendment 1: 50,000-byte compact JSON size cap, compact `get_measure_across_areas` rows + `data.measure` shared fields, `position` only on value sorts, `get_area_values` skip-with-warning for unpublished levels, `sources` rules for non-value tools, `get_measure_details` keys (`measure_key` + `product` + `measure_id`), withheld-AHRF warnings/errors (with new traps `Q43` & `Q44`), and dynamic `without_value` null-value check on `Q42`. |
| M3c Accept contract item 2a | Done (`--validate` & `test_checks.py` 8/8 passing) | `agy/mcp-m3` | Updated `run_eval.py` and `test_checks.py` for item 2a (`2026-11-17T15:35:00Z`): `data.measure` requires `uncertainty_kind` and `uncertainty_label`, compact `get_measure_across_areas` rows forbid `kind`/`label` in `uncertainty`, and row interval keys are checked against `data.measure.uncertainty_kind` (`ci95` → `low`/`high`, `moe90` → `moe`, `none` → `{}`). |

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

## Coverage counts (`backend/tests/mcp_eval/questions.yaml` after M3b)

- **Total questions:** 44 (32 standard + 12 trap questions)
- **Total tool calls:** 65
  - `get_area_values`: 20
  - `get_measure_across_areas`: 16
  - `find_places`: 10
  - `search_measures`: 9
  - `get_area_context`: 6
  - `get_measure_details`: 2
  - `list_data_sources`: 2
- **Questions by product / facility block:**
  - `places`: 18, `acs_profile`: 14, `acs`: 8, `clh`: 8, `cms_gv`: 8, `usda_fea`: 7, `brfss`: 6, `epa_aqi`: 6
  - Facility blocks: `health_centers`: 6, `nursing_homes`: 6, `tri_facilities`: 6
  - Excluded product (`ahrf` traps): 3 (`Q33`, `Q43`, `Q44`)
- **Levels covered:** `county` (52), `tract` (19), `state` (16), `cd` (13)
- **Showcase & required geographies:** Person County NC (`37145`), Kanawha County WV (`54039`), Fresno County CA (`06019`), WV-01 (`5401`), Alabama (`01`), Texas (`48`, 254 counties), Los Angeles County (`06037`, 2,498 tracts).
- **Trap questions (12):**
  1. `Q33` (`ahrf_excluded`): `search_measures(query="primary care doctors")` (returns `measures: []` + withheld AHRF warning) and `get_area_values` for `ahrf:phys_nf_prim_care_pc_exc_rsdt_23` (raises `ToolError`).
  2. `Q34` (`time_trend_one_period`): multi-year trend request on `places:diabetes_crudeprev` in `54039`.
  3. `Q35` (`no_composite_score`): healthiest-county composite score request in Alabama (`01`).
  4. `Q36` (`epa_aqi_no_monitor`): `epa_aqi:median_aqi` in unmonitored county (`01001`) and across Alabama (`01`, 15 available / 52 `no_reported_value`).
  5. `Q37` (`kentucky_brfss_not_published`): Kentucky (`21`) 2023 `brfss:diabetes` (`not_published`) vs 2022 `brfss:dental_visit` (`available`), plus all-states `brfss:diabetes` (`21` and `42` in `without_value`).
  6. `Q38` (`cms_not_published_for_cd`): `cms_gv:std_payment_per_capita` requested at `level="cd"` for WV (`54` / `5401`) — `get_measure_across_areas` raises `ToolError`, while `get_area_values` skips `cms_gv:std_payment_per_capita` and warns with published levels (`state`, `county`).
  7. `Q39` (`tracts_require_county`): `get_measure_across_areas` at `level="tract"` with omitted `within` and with 2-digit state GEOID `within="37"`.
  8. `Q40` (`medicare_original_beneficiaries`): `cms_gv` measures in `37145` and `54039` checked for `"Original Medicare beneficiaries"` population label and general interpretation rule.
  9. `Q41` (`ct_pr_coverage_status`): Connecticut planning region `09110` (`boundary_not_comparable` in `usda_fea`) and Puerto Rico `72001` (`not_covered` in `usda_fea`, `not_published` in `cms_gv`).
  10. `Q42` (`limits_and_truncation`): 12 counties × 41 measures (492 rows > 400-row cap) error check in `get_area_values`, and 2,498 tracts in `06037` size-cap / truncation check in `get_measure_across_areas` verifying all null-value `without_value` rows from `lookup` (42 rows; 16 `open_ended` tracts carry values in `with_value`) are preserved.
  11. `Q43` (`ahrf_withheld_topic`): `topic="health-care-resources"` in `search_measures` and `get_area_values` raises `ToolError` with the withheld-AHRF explanation and never `"Unknown topic"`.
  12. `Q44` (`ahrf_withheld_queries`): `search_measures` queries for `"hospital beds"`, `"dentists"`, and `"psychiatrists"` return `measures: []` plus a warning naming `AHRF`, and `search_measures()` with no arguments lists the 6 public topics (omitting `health-care-resources`) with the exact withheld-topic warning.

## Note for Claude on Amendment 1 §2 byte math for 254 Texas counties (`Q16`)

When measuring size with `separators=(",", ":")`, 254 Texas county rows (`places:diabetes_crudeprev`) carrying full `area` (`{"level":"county","geoid":"48xxx","name":"..."}`), `value`, `status` (`"available"`), `status_text` (`"Published value"`), `uncertainty` (`{"kind":"ci95","low":...,"high":...,"label":"95% confidence interval"}`), and `position` still weigh ~228 bytes/row (254 × 228 + ~2,000 envelope ≈ **59,900 bytes**), which is ~10 KB over the 50,000-byte cap unless `area.level` / `uncertainty.label` are also omitted on compact rows (or `with_value` is truncated at 50,000 bytes). `run_eval.py` allows `area.level` and `uncertainty.label` to be either present or omitted on compact rows and does not hard-code `expected_truncated: false` on `Q16`, so whether Codex fits all 254 rows via compact `area`/`uncertainty` or truncates at 50,000 bytes, `Q16` will evaluate cleanly against `lookup`.

## Contract ambiguities found in `docs/mcp/TOOL_CONTRACT.md` (resolved in Amendment 1)

All 7 ambiguities recorded in M3 were settled by Amendment 1 in `docs/mcp/tasks/M3b-antigravity.md` and are now enforced in `run_eval.py` and `test_checks.py`.

## Diary facts (2026-11-17T15:27:00Z)

- **Task:** M3b alignment of the CHIP MCP evaluation suite with Contract Amendment 1 on branch `agy/mcp-m3` in `/home/john/chip-agy`.
- **Updated files:**
  - `backend/tests/mcp_eval/run_eval.py`:
    - Size check updated to `len(json.dumps(structured_content, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) <= 50_000`.
    - Enforced compact row shape and `data.measure` shared metadata on `get_measure_across_areas` while keeping full row checks on `get_area_values`.
    - Enforced `position` only on `get_measure_across_areas` `with_value` rows when `sort` is `value_desc` or `value_asc`, and forbidden on `sort="geoid"`, `without_value`, and `get_area_values`.
    - Updated `expect_unpublished_level_handled` (`Q38`) to require `get_area_values` to skip unpublished measures with a warning naming published levels rather than raising `ToolError`.
    - Enforced `sources` matching on non-value tools (`find_places` -> `[]`, `get_measure_details` / `search_measures` -> products in `data.measures`) and required `measure_key`, `product`, and `measure_id` on `get_measure_details` items.
    - Added withheld-AHRF warning and `ToolError` checks (Item 7).
  - `backend/tests/mcp_eval/questions.yaml`:
    - Updated `Q24` and `Q33` for Amendment 1 §7; removed hard-coded `expected_without_value_count: 58` from `Q42` so `without_value` is checked dynamically from `lookup` null-value rows (42 rows).
    - Added trap questions `Q43` (`ahrf_withheld_topic`) and `Q44` (`ahrf_withheld_queries`), bringing the suite to 44 questions (32 regular + 12 traps, 65 tool calls).
  - `backend/tests/mcp_eval/test_checks.py`:
    - Expanded to 8 offline unit tests covering all Amendment 1 checks.
  - `docs/mcp/status/antigravity.md`: added M3b status row and diary facts.
- **Verification run in sandbox:**
  - `backend/.venv-mcp/bin/python -m py_compile backend/tests/mcp_eval/run_eval.py backend/tests/mcp_eval/test_checks.py` -> exit 0.
  - `PYTHONPATH=backend backend/.venv-mcp/bin/python backend/tests/mcp_eval/run_eval.py --validate` -> Validation PASSED (44 questions, 12 traps, 65 tool calls).
  - `PYTHONPATH=backend backend/.venv-mcp/bin/python -m pytest backend/tests/mcp_eval/test_checks.py -v` -> 8 passed in 0.60s.
- **Next action:** Claude runs `--expected-only` and `--url http://127.0.0.1:8011/mcp` after Codex finishes M2b, then commits `agy/mcp-m3`.

## Diary facts (2026-11-17T15:08:00Z — M3 initial build)

- **Task:** M3 independent evaluation suite for the CHIP MCP server on branch `agy/mcp-m3` in `/home/john/chip-agy`.
- **Created files:** `backend/tests/mcp_eval/__init__.py`, `backend/tests/mcp_eval/questions.yaml`, `backend/tests/mcp_eval/run_eval.py`, `backend/tests/mcp_eval/test_checks.py`, `deliverables/mcp/eval_report.md`.
