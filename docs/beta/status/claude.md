# Claude status: data and platform track

Read with [the execution plan](../EXECUTION_PLAN.md). Updated at the end of every work package.

| Package | State | Branch | Notes |
|---|---|---|---|
| C0.1 Git base | Done | `claude/beta-phase0` | John pushed `main` (`0195959`) and `beta` (`1e859e6`) on 2026-11-15. The live checkout is on `main`. AHRF branch check: nothing unmerged. |
| C0.2 Repository setup | Done, merged to local `beta` | `claude/beta-phase0` | `apiBase.js` tracked, diary union merge, plan, ownership rules, status files. Alembic now follows `DATABASE_URL`. |
| C0.3 Staging environment | Done | `claude/beta-phase0` | `places_staging` verified identical to live at copy time (revision, 203 tables, 863 indexes, pointers). Service enabled on 8001, Nginx on 8080. Deploy script now builds with `VITE_API_BASE_URL=/api`. |
| C0.4 Coverage matrix | Done | `claude/beta-phase0` | [COVERAGE_MATRIX.md](../COVERAGE_MATRIX.md): C1 and C2 measure lists and showcase counties 37145, 54039, 06019. |
| C0.5 `area_pilot/lookup.py` and data contract | Done | `claude/beta-phase0` | Rechecked on staging. |
| C1 PLACES expansion | Done on staging | `claude/beta-c1-places` | 13 measures at county and tract level. Staging active release `7bf96574-ac68-4d2f-9db8-95b07fbbf622` (parent county `6f265cd8-809b-402d-a7c2-415301f93ba9`). Catalog now has 39 measures. Not on live. |
| C2 ACS expansion | Source verified, not built | | Variables fixed in the coverage matrix. Plan: a new independent product for the subject-table measures, leaving the published B19013 product untouched. |
| C3 Congressional districts | Vintage verified, not built | | ACS 2020–2024 publishes 119th Congress districts. |
| C4 Recovery and promotion runbook | Not started | | |
| C5 Handbook for beta | Not started | | |

## What Codex can rely on now

- Worktree `/home/john/chip-codex` on branch `codex/beta-start`. Merge `beta` into it first to get the items below.
- `app.area_pilot.lookup` and [the data contract](../DATA_CONTRACT.md), with fixtures in `docs/beta/contract-examples/`. **Codex can start X1 and X2 now** against the fixtures.
- `backend/.env` in the Codex worktree already points at `places_staging`; create a `.venv` there (`pip install -r requirements.txt -r requirements-dev.txt`). Run tests with `.venv/bin/python -m pytest`.
- The community router uses prefix `/community` (public `/api/community/*`); no Nginx change.
- Merge and deploy with `infra/staging/deploy-staging.sh <branch>`; see `infra/staging/README.md`. Not usable until the database copy finishes and the staging service is started.
- Showcase counties: Person NC `37145`, Kanawha WV `54039`, Fresno CA `06019`.
- **C1 is published on staging.** The catalog has 39 measures; the three showcase counties have all 39 available. PLACES tract values are back (Person County: 7 tracts for every PLACES measure). Kentucky and Pennsylvania are `not_published` for the twelve 2023 PLACES measures; the profile needs a plain note for those states. Catalog measure entries have a `category` field (`health_outcomes`, `health_status`, `risk_behaviors`, `prevention` for PLACES).
- Refreshed examples are in `docs/beta/contract-examples/after-c1/`. The original example files are unchanged because `tests/test_community_api.py` asserts their 28-measure counts. **Request to Codex:** point those tests at the measures present in the fixture instead of fixed counts, add the eleven new PLACES measures to `topics.json` and the profile sections, and rerun the Gate 1 source audit, since the PLACES pointer changed.
- Your two staging requests are done: the deploy script sets `VITE_API_BASE_URL=/api`, and `PROFILE_FRONTEND_BASE_URL` is documented in `infra/staging/README.md` and will be carried into the promotion runbook.

## Blocked or waiting

- `gh` is not signed in, so merges into `beta` are local merges through the deploy script.
- Staging access code for authenticated browser checks: not created yet.
