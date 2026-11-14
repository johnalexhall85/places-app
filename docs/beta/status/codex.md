# Codex status: product track

Read with [the execution plan](../EXECUTION_PLAN.md). Codex updates this file at the end of every work package.

| Package | State | Branch | Notes |
|---|---|---|---|
| X1 Community API | In progress; local tests passed, staging pending | `codex/beta-x1-community-api` | `/community` search, catalog, county profile, comparison, facilities, tract reads, topics, and CSV are implemented through `app.area_pilot.lookup`. Focused tests: 13 passed. Full suite: 655 passed, two source-dependent failures with ignored inputs absent; the known FY2026 source mismatch remains when inputs are linked. Restore and staging deploy still pending. |
| X2 Landing, navigation, county profile, brand tokens | Not started | | |
| X3 Comparison and PDF export | Not started | | |
| X4 Topics and tract patterns | Not started | | |
| X5 District briefing | Waiting for C3 | | |
| X6 End-to-end tests and polish | Not started | | |

## What Claude can rely on now

- The X1 API can be reviewed on `codex/beta-x1-community-api`; no changes to Claude-owned paths or live systems. The seven topic definitions are initial product copy; C1 and C2 measures must be added when published.

## Blocked or waiting

- Staging database restore and first staging deployment are still pending. X1 can be merged and deployed after the copy completes and the service starts.
