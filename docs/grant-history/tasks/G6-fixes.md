# Task G6: small fixes before Gate A (2026-11-20)

The ownership and rules from your earlier task file apply (G1G2-codex.md or G3-antigravity.md):
- Do not commit.
- Never edit the diary or the handbook.
- Write normally formatted source.

Add a `G6` row and a `## G6 diary facts — <ISO timestamp>` section to your status file. Finish with a report of 10 lines or fewer.

## Codex (`/home/john/chip-codex-state`)

1. **Details panel at 375 px.** The expanded details panel sits inside the horizontally scrolling table, so its right side is cut off. Below 640 px, render recipient rows as stacked cards (name, type, project title, amount), with the details panel at full card width. Take Chromium screenshots at 375 px with a row expanded, and confirm that the panel's right edge is inside the viewport.
2. **Group order.** In the Recipients section, the `'__'` group ("State not recorded") must always come last, and states with only past awards come after funded states, for every sort and direction. This is what contract §2 says for `by_state`. Use `CDC-RFA-TU-24-0137`, where `'__'` has $1,268,643, as a vitest case.

## Antigravity (`/home/john/chip-agy-state`)

For this task, you also own `backend/tests/mcp_eval/run_eval.py` and `backend/tests/mcp_eval/test_checks.py`.

1. Add `get_state_funding`, `list_state_grants`, and `get_grant_history` to `ALL_TOOLS`, along with any lookup or check handlers that Q67–Q72 need.
2. Update the expected question count in `test_checks.py` to 72.
3. Run these under `/home/john/chip-claude/backend/.venv-mcp/bin/python`, and record the results:
   - `run_eval.py --validate`;
   - `pytest backend/tests/mcp_eval/test_checks.py`;
   - the offline check of Q67–Q72 against staging.
