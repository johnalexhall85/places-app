# Task F1+F2 (Codex): funding_report build and lookup, MCP funding tools, dataset route

Assigned by Claude on 2026-11-18. Work in `/home/john/chip-codex-funding`, on branch `codex/funding-report`, which is already checked out. You own `backend/app/funding_report/**`, `backend/app/mcp_server/**`, `backend/tests/test_funding_report_*`, `backend/tests/test_mcp_*`, and `docs/funding-mcp/status/codex.md`. Do not commit, push, merge, deploy, or use sudo. When you finish, record your facts in `docs/funding-mcp/status/codex.md` and stop.

**Read first:** [docs/funding-mcp/PLAN.md](../PLAN.md), which is the specification and contains the dataset JSON contract `chip.nofo_recipient_profile.v1`, and Amendment 3 in [docs/mcp/TOOL_CONTRACT.md](../../mcp/TOOL_CONTRACT.md). Port the method from [build_ce24_0027_recipient_dossier.py](../../../backend/scripts/build_ce24_0027_recipient_dossier.py) and [build_nofo_subawardee_reports.py](../../../backend/scripts/build_nofo_subawardee_reports.py), but take obligations from the account-level table as the plan says. The source scripts have a bug: they read `legal_entity_zip`, but the column is `legal_entity_zip_code`.

**Database:** `backend/.env` points to `places_staging`, which has the `funding_report` schema (migration `b3f9d2a7c1e4`, already applied) and the same source data as live. Do not create migrations; ask in your status file if the schema has to change. You may run the build against `places_staging` only.

## F1: `backend/app/funding_report/`

1. **`keys.py`:** `nofo_key(text) -> str | None` as the plan defines it.
2. **`build.py`:** `python -m app.funding_report.build [--database-url URL]`.
   - Insert a `build_run` row with status `running` and `method_version` `nofo-v1`.
   - Compute everything with set-based SQL (temporary tables are fine). Do not issue one query per NOFO.
   - Cover **every** CDC NOFO key found in USAspending prime transactions (any source fiscal year), plus TAGGS `opdiv = 'CDC'` FON values.
   - TAGGS FONs from other OpDivs become `nofo` rows with `summary.supported = false` and `summary.opdiv`, with no awards, so that lookups can refuse them clearly.
   - An award belongs to a NOFO when any of its transactions carries that FON. Its account-level rows then count in **every** fiscal year, including FY2019 and FY2020 rows with an empty FON.
   - Write `nofo`, `nofo_award.profile`, `uei_award` (every UEI that appears in any `nofo_award`), and `nofo_subaward`.
   - `build_run.sources` records the coverage and data-through values for each source: the max `action_date`, the max sub-award action date, the TAGGS max `action_issue_date`, and the account FY/period and `is_complete` flags from `cdc_funding.cdc_funding_import_runs`. `counts` records the row counts.
   - In **one transaction**: set the build to `complete`, upsert `active_build`, mark the older builds `superseded`, and delete all but the newest 2 builds. A failure marks the build `failed` and leaves `active_build` unchanged.
   - Print a one-line JSON summary. Target: under 10 minutes on staging.
3. **`lookup.py`:** the only API the MCP server may use.
   - `active_build(session) -> dict | None`
   - `resolve_nofo(session, text) -> dict`: returns the match, or raises `FundingLookupError` with up to 5 suggestions found by substring and key prefix in `nofo.search_text`. Raises a distinct error type for an unsupported, non-CDC NOFO.
   - `nofo_overview(session, key, include_subawards)`
   - `list_recipients(session, key, offset, limit)`
   - `recipient_profile(session, key, recipient)`
   - `nofo_dataset(session, key, include_subawards) -> dict`: exactly the v1 contract.
   - Use SQLAlchemy `text()` with bound parameters. Every query reads only the active build.
4. **Tests (`backend/tests/test_funding_report_unit.py`):** pure-function tests for key normalization, the best-available basis, the district source order, sub-award deduplication, and the caveats.
5. **Tests (`backend/tests/test_funding_report_staging.py`):** skipped when staging has no active build. On staging, for `CDC-RFA-PS21-2102`, assert:
   - 97 recipients;
   - FY2021–FY2025 account obligations of 42,395,995 / 49,347,654 / 52,613,214 / 42,395,995 / 42,395,995 (rounded to dollars);
   - FY2026 ≈ 10,166,689;
   - the dataset validates against the contract keys.
   
   Also record the PS21-2102 other-award top-10 total, the number of other-award rows, and the HRSA count and total (the reference has $2,025,515,221, 485 rows, and HRSA 266 / $1,382,809,067), and the CE23-2301 sub-award summary (the reference has 5 sub-awardees, 12 actions, and $1,962,872.68). Assert them where they match. Where they don't, explain the difference in the status file.

## F2: MCP server (`backend/app/mcp_server/`)

1. **Tools:** add `get_nofo_overview`, `list_nofo_recipients`, and `get_recipient_funding` to `tools.py`. Register them in `app.py` with descriptions written for a model and the same read-only annotations as the existing tools.
   - The descriptions say: CDC funding opportunities only; amounts come with sources; get the `dataset_url` from `get_nofo_overview` to build full reports.
   - Reuse `_run()`. The cache key must include the active funding build id, so either generalize `_run` or add a funding variant; area tools must behave exactly as before.
   - Map `FundingLookupError` to an actionable `ToolError`.
2. **Envelope:** funding `sources` come from the dataset's `sources` entries (keep the `Envelope` field shape), and `interpretation_rules` are the five funding rules from the plan, verbatim. Respect the 50,000-byte cap with `fit_rows()` semantics. Trim only recipient lists, and set `truncated`.
3. **Dataset route:** `GET /funding/nofo/{nofo_key}.json?subawards=0|1` on the same Starlette app, next to `/healthz`.
   - Response: gzip JSON, `Cache-Control: public, max-age=3600`, and an `ETag` of `"<build_id>-<key>-<subawards>"`. Return 304 on a matching `If-None-Match`.
   - Errors: a JSON 404 body on an unknown key, and a 422 for an unsupported NOFO.
   - Cache the encoded body in-process, keyed by build, key, and sub-awards.
4. **Dataset URL:** `get_nofo_overview` returns an absolute `dataset_url` built from the new env var `CHIP_MCP_PUBLIC_BASE_URL` (default `http://127.0.0.1:8011`). Document the variable in `config.py`.
5. **Server instructions:** add one funding sentence and keep the text under 1,200 characters. Fix the "eight tools" wording.
6. **Tests:** update `test_mcp_unit.py` and `test_mcp_integration.py`, including the tool count (now 11). Add unit tests for the funding tools with lookup stubbed: envelope shape, rules, errors, and the size cap. Add a route test using Starlette's `TestClient` that covers gzip, the ETag, 304, 404, and 422.
   - Run `cd backend && PYTHONPATH=. .venv-mcp/bin/python -m pytest tests/test_mcp_* tests/test_funding_report_* -q`.
   - Also run the area-tool regression `tests/mcp_eval/run_eval.py --expected-only` if it runs without a server. Report any failure.

## Finish

1. Run the build once on staging and give the build id, duration, and counts.
2. Paste test results.
3. Write `docs/funding-mcp/status/codex.md`: what you built, the numbers from F1.5, any deviations from the plan, and open questions.

Report in eight lines or fewer.
