# Task F4 (Antigravity): funding evaluation questions and fidelity report

Assigned by Claude on 2026-11-18. Work in `/home/john/chip-agy-funding`, on branch `agy/funding-eval` (based on `codex/funding-report`, already checked out). Run Python as `cd backend && PYTHONPATH=. .venv/bin/python ...` (it has PyYAML and pytest).

**You own:**
- the funding additions to `backend/tests/mcp_eval/**`;
- `deliverables/funding-mcp/**`;
- `docs/funding-mcp/status/antigravity.md`.

Do not commit, deploy, or use sudo. Make no network calls except to `http://127.0.0.1:8011`. Record your facts in the status file and stop.

**Read first:**
- [docs/funding-mcp/PLAN.md](../PLAN.md);
- Amendment 3 in [docs/mcp/TOOL_CONTRACT.md](../../mcp/TOOL_CONTRACT.md);
- the existing `backend/tests/mcp_eval/questions.yaml` and `run_eval.py`.

## Requirements

1. **Questions.** Add 12 funding questions in the existing YAML format, with the expected values computed from `app.funding_report.lookup` (in the same way that area questions use `app.area_pilot.lookup`). Cover:
   - **NOFO match (3):** `CDC-RFA-PS21-2102`, `ps21 2102`, and `CE23-2301`.
   - **Totals by fiscal year (2):** check that values match the account-level obligations.
   - **No match (1):** expect suggestions.
   - **A non-CDC FON taken from TAGGS (1):** expect a refusal that names the operating division.
   - **Sub-awards (2):** one trap where the user asks for "total funding including sub-awards". The correct answer refuses to add them.
   - **`list_nofo_recipients` paging (1).**
   - **`get_recipient_funding` (2):** look up by UEI, and look up by a name substring.

   Funding checks:
   - every response has funding `sources` and the 5 funding `interpretation_rules`;
   - responses stay under 50,000 bytes;
   - `dataset_url` is present;
   - no area-product sources appear in funding answers, and no funding sources appear in area answers.
2. **Dataset check.** Add an `--dataset-check` mode that fetches `GET /funding/nofo/PS212102.json?subawards=1` from the server under test and validates the v1 contract:
   - every key is present;
   - recipients are sorted by state, then name;
   - each `fiscal_years` list is ordered;
   - null values are never written as 0 in money fields that had no source rows.
3. **Runs.**
   - `--validate`, then `--expected-only`.
   - Then `--url http://127.0.0.1:8011/mcp`, once Claude tells you that staging serves the funding tools. If it doesn't yet, report the expected-only result only.
   - The existing area questions must still pass unchanged.
4. **Fidelity report.** Write `deliverables/funding-mcp/fidelity_report.md`, comparing PS21-2102 from `lookup` with John's reference workbook `/home/john/places-app/data/cdcfundingprofiles/PS21-2102_Recipient_Dossier.xlsx`.
   - Compare the recipient count, per-recipient FY2021–FY2025 totals, other-award counts and top-10 totals, and the OpDiv rollup.
   - List every recipient whose values differ, with the reason when the data explains it (for example, a later data date or the account-level versus award-level basis).
   - Do the same for CE23-2301 sub-awards against `/home/john/places-app/data/reports/ce23_2301_subawardees/`.

Report in six lines or fewer.
