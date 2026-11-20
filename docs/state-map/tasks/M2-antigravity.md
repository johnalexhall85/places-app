# Task M2 (Antigravity): state funding map audit and walkthrough checklist

Assigned by Claude on 2026-11-20. Work in `/home/john/chip-agy-state` on branch `agy/state-map`. Claude has copied Codex's M1 backend into this worktree so the `/map` endpoints exist.

**You own:** `backend/tests/test_state_map_audit.py`, `deliverables/state-map/**`, and `docs/state-map/status/antigravity.md`. Edit nothing else.

**Rules:** do not commit, push, merge, deploy, or use sudo. Write no database rows. Make no network calls other than to the local `places_staging` database. Never edit the project diary or handbook.

## Read first

[PLAN.md](../PLAN.md), [CONTRACT.md](../CONTRACT.md) (especially §2 and §5), and `backend/tests/test_state_funding_audit.py`, whose structure and staging-skip pattern you should follow.

## Steps

1. Write `backend/tests/test_state_map_audit.py` covering contract §5 invariants 1–5. Call the API in-process with FastAPI's `TestClient` and the demo-access override used by the state funding audit, and query `state_funding` directly for the obligation sums. Skip cleanly when the database is unreachable.
2. Include contract Amendment 1 (`deobligations=exclude`) in the invariants.
3. Run it: `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_state_map_audit.py -v`. Report the number of checks and the largest dollar difference.
4. Write `deliverables/state-map/walkthrough.md`: a checklist for John's staging tryout (each dropdown, the "Exclude deobligations" check box, a tooltip, the California panel and both links, a negative state such as Georgia in FY2026 all funding, the DC and Guam tiles, the table, and phone width).

## Report

Update `docs/state-map/status/antigravity.md` with the results, any invariant that fails with its figures, and open questions. Then stop.
