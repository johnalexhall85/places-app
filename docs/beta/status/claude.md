# Claude status: data and platform track

Read with [the execution plan](../EXECUTION_PLAN.md). Updated at the end of every work package.

| Package | State | Branch | Notes |
|---|---|---|---|
| C0.1 Git base | Partly done | `claude/beta-phase0` | `beta` and the three worktrees exist locally at `0195959`. Moving and pushing `main`, and pushing `beta`, were blocked by the session permission policy and wait for John. AHRF branch check: nothing unmerged. |
| C0.2 Repository setup | Done on branch, not pushed | `claude/beta-phase0` | `apiBase.js` tracked, diary union merge, plan, ownership rules, status files. |
| C0.3 Staging environment | Not started | | |
| C0.4 Coverage matrix | Not started | | |
| C0.5 `area_pilot/lookup.py` and data contract | Not started | | Codex starts after this merges to `beta`. |
| C1 PLACES expansion | Not started | | |
| C2 ACS expansion | Not started | | |
| C3 Congressional districts | Not started | | |
| C4 Recovery and promotion runbook | Not started | | |
| C5 Handbook for beta | Not started | | |

## What Codex can rely on now

- Worktree `/home/john/chip-codex` on branch `codex/beta-start`, based on `beta`.
- Nothing else yet. Staging and `app.area_pilot.lookup` do not exist.

## Blocked or waiting

- Push of `main` and `beta` to `origin` (John).
