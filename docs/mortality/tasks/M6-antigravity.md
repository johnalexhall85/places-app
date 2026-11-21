# Task M6 (Antigravity): "Death rates" section on county and state profiles

Assigned by Claude on 2026-11-21, at John's request. Work in `/home/john/chip-agy-mort` on branch `agy/mortality`, after M1–M3 are committed there.

**You own, for this task only:**
- New files: `backend/app/community/deaths.py` and `backend/tests/test_community_deaths.py`.
- Additions only (no rewrites) to:
  - `backend/app/community/router.py`: two routes beside `/hazards`.
  - The county and state profile page components under `frontend/src/community/`: the new section and skipping the mortality products elsewhere, exactly as the SVI and NRI hazard section does. Find the files with `grep -rn hazards frontend/src/community`.
  - Their tests, and `frontend/scripts/beta-walkthrough.mjs` if it lists the profile sections.
- `docs/mortality/status/antigravity.md`.

Edit nothing else.

**Rules:**
- Do not commit, push, merge, deploy, or use sudo.
- Make no network calls, and write no database rows.
- Never edit the diary, the handbook, `AGENTS.md`, or `alembic/`.
- Write normally formatted source.

## Read first
- [CONTRACT.md](../CONTRACT.md) §5, then §1–§3 for the labels and limitations.
- The template, which you wrote in VH3 and VH4: `backend/app/community/hazards.py`, its routes, `backend/tests/test_community_hazards*.py`, and the hazard section components.

## Steps
1. `deaths.py`: `build_county_deaths(db, info)` and `build_state_deaths(db, info)`, reading only through `lookup.area_values` as §5 states. A product with no active release returns an empty group, not an error.
2. Add the routes, then the tests: a fixture-backed county and state response, a suppressed row, an empty group, and the absence of `drug_poisoning` on the state response.
3. Add the frontend section per §5, skip the mortality products in the other sections, and add component tests.
4. Run:
   - `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_community_deaths.py tests/test_community_hazards*.py tests/test_community_api.py tests/test_community_state.py tests/test_community_charts_api.py -q`
   - `git diff --exit-code docs/beta/contract-examples`
   - `cd frontend && npx vitest run && npm run build`

## Report
Add a `## M6` section to `docs/mortality/status/antigravity.md` with:
- the files changed
- every test command and its count
- any failures, with the reason
- open questions

Then stop.
