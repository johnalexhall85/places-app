# Task G3 (Antigravity): grant history audit, MCP eval questions, walkthrough checklist

Assigned by Claude on 2026-11-20. Work in `/home/john/chip-agy-state` on branch `agy/grant-history`. Claude merges Codex's reviewed G1+G2 code into this branch before you start.

- **Database:** `backend/.env` points at `places_staging`.
- **Backend tests:** `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest ...`
- **MCP code:** run it with `/home/john/chip-claude/backend/.venv-mcp/bin/python`.

**You own:**
- `backend/tests/test_grant_history_audit.py`
- new state funding and grant history questions in `backend/tests/mcp_eval/questions.yaml` (add questions; do not change existing ones)
- `deliverables/grant-history/**`
- `docs/grant-history/status/antigravity.md`

**Rules:**
- Do not commit, deploy, or use sudo.
- Make no network calls. Write no database rows.
- Do not edit any other file. If you find a defect in Codex's code, record it in your status file with the smallest reproduction; do not fix it.

## Read first

1. [PLAN.md](../PLAN.md) and the whole of [CONTRACT.md](../CONTRACT.md), especially §1 and §7.
2. Amendment 4 in [docs/mcp/TOOL_CONTRACT.md](../../mcp/TOOL_CONTRACT.md).
3. `backend/app/state_funding/lookup.py` (`grant_history`, `grant_award`, `grants`, `summary`) and the three new tools in `backend/app/mcp_server/tools.py`.
4. `backend/tests/mcp_eval/questions.yaml` and `run_eval.py`, for the question format and how checks run.

## Build

1. `backend/tests/test_grant_history_audit.py` implements **every** invariant in contract §7.
   - Mark it `pytest.mark.integration`, and skip it cleanly when the database is unreachable.
   - Choose the NOFOs deterministically, as §7 says.
   - Every assertion message names the NOFO, fiscal year, state, and both values.
   - Invariant 7 calls the tool functions in-process under `.venv-mcp`; put it in a separate test that skips if `mcp` cannot be imported.
2. Run it, and record the pass or fail result of each invariant, with numbers, in your status file. If something fails, give the SQL reproduction and stop. Do not loosen tolerances.
3. Add 6 eval questions with checks:
   - two for `get_state_funding`: a state total for FY2026 grants, and its largest budget category;
   - two for `list_state_grants`: find a grant by NOFO number in a state, and the top grant by amount;
   - two for `get_grant_history`: PS21-2102's latest fiscal year and its state with the largest total, and a past-recipient count.

   Take the expected values from SQL on staging.
4. Write `deliverables/grant-history/walkthrough.md`, a checklist for Claude and John on staging, with expected values from SQL:
   - **PS21-2102:** the latest FY, the latest-FY total, the number of recipients and states, the top three states with their totals, one recipient to search for by name and one by UEI, and the past-recipient count.
   - **The largest FY2026 NOFO:** the same items.
   - **One NOFO whose last funded year is before FY2026:** check the label.
   - **Generic checks:**
     - 375 px with no horizontal page scroll;
     - sorting;
     - the past toggle;
     - a lazy expand showing history and sub-awards;
     - the CSV;
     - the link from a state-page grant row and back;
     - an unknown NOFO showing suggestions;
     - an anonymous API request returning 401.
   - **Beta MCP connector prompts** to try in claude.ai, with the expected answers.

## Done when

`docs/grant-history/status/antigravity.md` has a row for G3 and a section `## G3 diary facts — <ISO timestamp with timezone>`. That section records:
- the commands run;
- the result of each invariant;
- the eval questions added;
- any defects found;
- the files created.

`git status` shows changes only in your owned paths. Finish with a report of 10 lines or fewer.
