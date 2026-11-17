# Task M3 (Antigravity): independent evaluation suite for the CHIP MCP server

Assigned by Claude Code (project manager), 2026-11-17. Worktree `/home/john/chip-agy`, branch `agy/mcp-m3` (checked out).

You are the **independent tester**. Codex is building the server at the same time from the same contract; you have not seen its code, and that is intended. Test the contract, not an implementation.

## Read first

1. `AGENTS.md`, especially "MCP server: three-agent ownership".
2. `docs/mcp/TOOL_CONTRACT.md`. **This is the specification.**
3. `docs/mcp/PLAN.md`.
4. `backend/app/area_pilot/lookup.py`. This is the ground truth for expected values; read only.
5. `backend/app/community/topics.json` and `docs/beta/COVERAGE_MATRIX.md`, to choose realistic questions.

## Build

Only in these paths: `backend/tests/mcp_eval/**`, `deliverables/mcp/**`, and `docs/mcp/status/antigravity.md`.

1. **`backend/tests/mcp_eval/questions.yaml`**: about 40 realistic questions a public-health analyst, journalist, or funder would ask. Spread them across every tool, every public product (`places`, `acs`, `acs_profile`, `brfss`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea`, plus the facility blocks), and the levels state, county, tract, and cd. Include the showcase places: Person County NC `37145`, Kanawha County WV `54039`, Fresno County CA `06019`, and district WV-01 `5401`. Include Alabama counties and Texas (254 counties). Each entry has:
   - `id`, `question` (natural language), `expected_calls` (an ordered list of `{tool, arguments}` a good assistant would make), and `checks`, for example:
     - Values equal to `lookup` output for named areas and measures.
     - A status and `status_text` on every row, and a citation on every row.
     - `uncertainty.kind` matching the product.
     - `sources` covering exactly the products in `data`.
   - **At least 8 trap questions**, each checking that the server gives the honest answer, not a convenient one:
     - Asking for AHRF physicians: the measure is excluded and the error explains why.
     - Asking for a time trend: one period only, said plainly.
     - Asking for a "healthiest county" composite: no composite score exists.
     - Asking for EPA AQI in a county with no monitor: `no_reported_value`, never 0.
     - Asking for a Kentucky BRFSS value: `not_published`.
     - Asking for district values from CMS: not published for `cd`.
     - Asking for tracts without a county: an actionable error.
     - Medicare questions: the population is labelled Original Medicare beneficiaries.
2. **`backend/tests/mcp_eval/run_eval.py`**: a deterministic runner, with no LLM in the loop.
   - `--url http://127.0.0.1:<port>/mcp` calls each `expected_calls` through the official client (`from mcp import Client`; `async with Client(url) as c: await c.call_tool(name, args)`, then read `result.structured_content`).
   - It computes expected values directly from `app.area_pilot.lookup` against the database in `backend/.env` (`places_staging`), then applies the checks.
   - Global checks on every response:
     - No `ahrf` anywhere in the serialized output.
     - Response size under 60,000 bytes.
     - No words "best", "worst", or "score" in keys or warnings.
     - `get_measure_across_areas` keeps every null-value area in `without_value`, numbers positions with ties (1, 2, 2, 4), and adds the ordering warning on value sorts.
     - Latency recorded, with p50 and p95.
   - `--expected-only` computes and prints the expected values without a server, so the question set can be validated before the server exists.
   - Exit code 0 only when every check passes.
3. **`deliverables/mcp/eval_report.md`**: written by the runner (`--report PATH`). Contents: a pass/fail table per question, failures with the expected and actual values, latency, the server URL, the commit, and a timestamp.
4. **`docs/mcp/status/antigravity.md`**: an M3 row with the state, the counts, and contract ambiguities you found. Ambiguities are valuable: list each one with the contract section it concerns.

## Environment

- Python venv: `backend/.venv-mcp` already exists with `mcp==2.3.0`, `pyyaml`, `pytest`, and the database libraries. Run with `cd backend && PYTHONPATH=. .venv-mcp/bin/python tests/mcp_eval/run_eval.py ...`.
- **The server may not exist yet.** If `backend/app/mcp_server/` is absent, finish everything and validate with `--expected-only`. Claude runs the full eval against the server in M4. Do not write a server yourself.

## Rules

- **Do not commit, push, merge, deploy, run sudo, start long-lived services, or edit files outside your paths.** Claude reviews and commits.
- Put diary-worthy facts in your status file, not in `docs/PROJECT_DIARY.md`.
- Read-only database access only. Never write to the database.

## Done when

1. `--expected-only` runs cleanly and prints expected values for every question.
2. If the server exists: the full run completes and the report is written, even when checks fail (failures are useful findings).
3. The status file is updated. Finish with a short report: files created, question count by tool and product, trap questions, contract ambiguities, and how to run it.
