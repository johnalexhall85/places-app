# Claude status: data and platform track

Read with [the execution plan](../EXECUTION_PLAN.md). Updated at the end of every work package.

| Package | State | Branch | Notes |
|---|---|---|---|
| C0.1 Git base | Partly done | `claude/beta-phase0` | `beta` and the three worktrees exist locally at `0195959`. Moving and pushing `main`, and pushing `beta`, were blocked by the session permission policy and wait for John. AHRF branch check: nothing unmerged. |
| C0.2 Repository setup | Done, merged to local `beta` | `claude/beta-phase0` | `apiBase.js` tracked, diary union merge, plan, ownership rules, status files. Alembic now follows `DATABASE_URL`. |
| C0.3 Staging environment | In progress | `claude/beta-phase0` | Service unit, Nginx site (port 8080), deploy script, worktree `.env` files, and virtual environments are in place. `places_staging` is being copied from live (70 GB). The staging backend has not been started and no staging access code exists yet. |
| C0.4 Coverage matrix | Done | `claude/beta-phase0` | [COVERAGE_MATRIX.md](../COVERAGE_MATRIX.md): C1 and C2 measure lists and showcase counties 37145, 54039, 06019. |
| C0.5 `area_pilot/lookup.py` and data contract | Done; staging check pending | `claude/beta-phase0` | Module, 9 unit tests, [DATA_CONTRACT.md](../DATA_CONTRACT.md), real examples in `contract-examples/`. Checked read-only against the live releases; to be rechecked on staging once the copy finishes. |
| C1 PLACES expansion | Code done, not staged | `claude/beta-c1-places` | Registries widened to 13 measures; measure-set release identity added; 35 unit tests pass. Source verified. Waiting for the staging database to stage, review, and publish. Not merged to `beta`. |
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
- Coming in C1: eleven more PLACES measures (2023). Kentucky and Pennsylvania are `not_published` for all of them; the profile needs a plain note for those states. Catalog entries gain a `category` field (`health_outcomes`, `health_status`, `risk_behaviors`, `prevention`).

## Blocked or waiting

- Push of `main` and `beta` to `origin` (John). Until then `beta` exists only on this VM.
- `gh` is not signed in, so merges into `beta` are local merges through the deploy script.
- Staging access code for authenticated browser checks: not created yet.
