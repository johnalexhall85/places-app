# Task M2b (Codex): fix round after the first evaluation

Assigned by Claude, 2026-11-17. Branch `codex/mcp-m2b` (checked out). The same rules as `docs/mcp/tasks/M2-codex.md` apply: owned paths only, no commits, no deploys, record facts in `docs/mcp/status/codex.md`.

The independent evaluation (Antigravity, 42 questions, against `chip-mcp-staging`) passed 40/42. Both failures were size overruns in `get_measure_across_areas` (Texas counties 63,876 bytes; Los Angeles tracts 63,103 bytes), because the server measures size differently from the client. Implement the contract amendment below everywhere it applies, and update or add tests in `backend/tests/test_mcp_*.py`. In particular, test that all 254 Texas counties for `places:diabetes_crudeprev` fit under 50,000 bytes measured as in item 1, and test each item of point 7.

Done when the full `tests/test_mcp_*.py` suite passes against `places_staging` (integration not skipped) and the status file has an M2b row. Report briefly: what changed, test counts, and anything you disagree with.

## Amendment 1 (2026-11-17, Claude): settles the first evaluation run and Antigravity's ambiguities

Where this differs from the sections above, this wins.

1. **Response size.** Size means `len(json.dumps(structured_content, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))`, where `structured_content` is the envelope as the client receives it. The cap is **50,000** bytes. Server and evaluation measure size the same way.
2. **Compact rows in `get_measure_across_areas`.** Fields shared by every row move once into `data.measure`: `measure_key`, `label`, `unit`, `storage_scale`, `period`, `population`, `value_type`, `release_id`, `boundary_vintage` (when the same on every row; otherwise keep it per row), and `citation`. Rows in `with_value` and `without_value` carry only `area`, `value`, `status`, `status_text`, `uncertainty`, and `notes` (omit `notes` when empty), plus `position` in `with_value`. All 254 Texas counties must fit under the cap. `get_area_values` keeps full rows.
3. **`position`** appears only in `get_measure_across_areas` rows, and only when `sort` is `value_desc` or `value_asc`. It is never emitted as null elsewhere. With `sort="geoid"` there is no position.
4. **Unpublished level.** `get_area_values` skips the measure with a warning naming the published levels. `get_measure_across_areas` raises `ToolError`, because it is about one measure. The "Errors" section is read this way.
5. **`sources` on tools that return no value rows** list the products whose metadata appears in `data`. Use an empty list when there are none (`find_places`).
6. **`get_measure_details`** items carry `measure_key` as well as `product` and `measure_id`.
7. **Withheld AHRF content must be explained, not hidden.**
   - `search_measures` with no arguments lists only public topics and adds a warning: "The topic 'Health care resources' (HRSA AHRF workforce and hospital measures) is on the CHIP website but not available through this public server."
   - `topic="health-care-resources"` in `get_area_values` or `search_measures` raises a `ToolError` with the same explanation, never "Unknown topic".
   - A `search_measures` query that matches only withheld AHRF measures (for example "primary care doctors", "hospital beds", "dentists", "psychiatrists") returns no measures plus a warning naming the withheld product.
8. **Null value.** An area belongs in `without_value` exactly when `value` is null. Statuses such as `open_ended` can carry a value and then belong in `with_value`. For Los Angeles County tracts and `acs:B19013_001E` that is 42 rows, not 58.
