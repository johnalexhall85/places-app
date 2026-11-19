# Task S4 (Antigravity): state funding reconciliation audit and walkthrough checklist

Assigned by Claude on 2026-11-19. Work in `/home/john/chip-agy-state` on branch `agy/state-funding`. Claude has already merged Codex's `backend/app/state_funding` into this branch. `backend/.env` points at `places_staging`, and an active build exists there. Run Python as `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest ...`.

**You own:**
- `backend/tests/test_state_funding_audit.py`
- `deliverables/state-funding/**`
- `docs/state-funding/status/antigravity.md`

Do not commit, deploy, or use sudo. Make no network calls. Write no database rows: read-only SQL and in-process function calls only. Do not edit any other file. If you find a defect in Codex's code, record it in your status file; do not fix it.

## Read first

1. [PLAN.md](../PLAN.md) and the whole of [CONTRACT.md](../CONTRACT.md), especially §1 and §5. **Amendment 1** at the end of the contract overrides earlier sections: audit `by_category` (not `by_account`) and add invariant 7 (crosswalk coverage and category = sum of its accounts). In the walkthrough, list the top three **budget categories**.
2. `backend/app/state_funding/lookup.py` and `router.py` (Codex's code).
3. `backend/app/cdc_funding_api/service.py` (`get_overview`), the source of the national `/cdc-funding` totals.

## Build

1. `backend/tests/test_state_funding_audit.py` implements **every** invariant in contract §5 against the active build on `places_staging`.
   - Mark it `pytest.mark.integration`, and skip it cleanly when the database is unreachable or has no active build.
   - Use SQL through SQLAlchemy and the `app.state_funding.lookup` functions.
   - For invariant 2, call `app.cdc_funding_api.service.get_overview` in-process.
   - Choose the 10 states for invariants 3–4 deterministically: CA, TX, NY, GA, WY, VT, DC, PR, AK, plus the state with the most negative FY2025 supplemental total.
   - Every assertion message names the fiscal year, filters, state, and both values.
2. Run it and record the pass/fail per invariant, with numbers, in your status file. If something fails, give the smallest reproduction (SQL) and stop. Do not loosen tolerances to make it pass.
3. `deliverables/state-funding/walkthrough.md`: a checklist Claude and John can follow on staging for CA, TX, WY, DC, and PR. For each state, for FY2026:
   - the expected total, regular, and supplemental amounts and the award count, taken from your SQL, so the page can be checked against them;
   - the top three budget categories;
   - one grant to search for by FAIN, and one by NOFO number;
   - the expected first row when sorted by amount;
   - what to check with Recipient type = State government.
   Also include generic checks: phone width (375 px, no horizontal page scroll), CSV download, the filter chips, the link from `/state/{fips}` (the community state profile), and a negative supplemental value shown with its sign.

## Done when

`docs/state-funding/status/antigravity.md` has a row for S4 and a section `## S4 diary facts — <ISO timestamp with timezone>`. That section records:
- the commands run;
- the results per invariant;
- any defects found;
- the files you created.

`git status` shows changes only in your owned paths. Finish with a report of 10 lines or fewer.
