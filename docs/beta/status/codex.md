# Codex status: product track

Read with [the execution plan](../EXECUTION_PLAN.md). Codex updates this file at the end of every work package.

| Package | State | Branch | Notes |
|---|---|---|---|
| X1 Community API | Done; merged and deployed to staging | `codex/beta-x1-community-api` | Staging `beta` at `6f76e0d`; authenticated Nginx reads passed for catalog, search, county profile, comparison, facilities, topics, tract route, and CSV. Local focused tests: 13 passed. Full suite: 655 passed, two unrelated source-dependent failures with ignored inputs absent; the known FY2026 source mismatch remains when inputs are linked. |
| X2 Landing, navigation, county profile, brand tokens | Done; merged and deployed to staging | `codex/beta-x2-landing-profile` | Staging `beta` at `8cd7412`. Root landing, `/explore/map` legacy route, county profile, brand tokens. Frontend 144/144 tests and Vite build passed; authenticated desktop/mobile browser walkthrough passed with 28 Person County cards, seven topic tiles, no page errors or horizontal overflow. Topic cards currently link to existing source maps; X4 adds topic pages. |
| X3 Comparison and PDF export | Not started | | |
| X4 Topics and tract patterns | Not started | | |
| X5 District briefing | Waiting for C3 | | |
| X6 End-to-end tests and polish | Not started | | |

## What Claude can rely on now

- The X1 API is available through staging Nginx. A staging-only access code is stored outside the repository at `/home/john/.local/share/chip/staging-beta-access-code` (mode 600); ask John to retrieve it on the VM for review. The seven topic definitions are initial product copy; C1 and C2 measures must be added when published.

## Blocked or waiting

- Staging's active PLACES pointer changed to county release `6f265cd8-809b-402d-a7c2-415301f93ba9` during C1. `lookup.county_tract_values` returned zero rows for Person County although retained tract releases contain seven rows. Recheck after C1 publishes its combined release; Codex did not change the pointer.
- The staging deploy script must build the frontend with `VITE_API_BASE_URL=/api`; without it the bundle calls the browser's `localhost:8000`. Codex redeployed X2 with that environment variable, but the script needs a durable staging default in Claude-owned `infra/staging/deploy-staging.sh` before the next package.
