# CHIP agent workflow

Follow the requester's instructions and any scoped nested `AGENTS.md` before changing files. The [project handbook](docs/PROJECT_HANDBOOK.md) is the entry point, and the [project diary](docs/PROJECT_DIARY.md) is the handoff record. They guide discovery; inspect implementation and runtime state before relying on a claim.

## At task start

1. Read the handbook, recent relevant diary entries, and linked operator documentation.
2. Inspect relevant code and, where the task depends on it, current database pointers, service state, deployment, or source files.
3. Report discrepancies and correct stale documentation during the task. Preserve historical entries and unrelated work.

## Before finishing

1. Update affected handbook sections when architecture, datasets, commands, deployment, or operational behavior changes. State what is deployed and what exists only in a branch.
2. Add a concise, reverse-chronological diary entry with an ISO 8601 timestamp and explicit timezone for meaningful code, data, deployment, decision, review, or question work. Record actual outcomes, state-changing commands, verification and failures, deployment status, unresolved issues, and next action. Label proposals and unverified claims. For read-only work, say that no application changes were made.
3. Include documentation changes in the task's intended commit when committing is authorized. Do not commit or push solely because of this workflow. Mention the diary and handbook status in the completion report.

## Funder beta: two-agent ownership (from 2026-11-14)

The [beta execution plan](docs/beta/EXECUTION_PLAN.md) governs the funder beta. Read it and both files in [docs/beta/status](docs/beta/status/) before each work package.

- **Claude Code owns** `backend/app/area_pilot/**`, `backend/alembic/**`, `infra/**`, `backend/docs/**`, `docs/PROJECT_HANDBOOK.md`, and `docs/beta/**` except Codex's status file. Only Claude creates migrations.
- **Codex owns** `backend/app/community/**`, `frontend/**`, `backend/tests/test_community_*`, `deliverables/**`, and `docs/beta/status/codex.md`. Codex reads published data only through `app.area_pilot.lookup`.
- Neither agent edits the other's paths. Record a needed change in your status file instead.
- Both agents add diary entries; the diary merges by union. Codex puts handbook-worthy facts in its diary entry and Claude folds them into the handbook.
- Work in your own worktree (`/home/john/chip-claude`, `/home/john/chip-codex`). Merge to `beta` by pull request without force, then run the staging deploy script. Do not merge to `main`.
- Until John approves promotion, do not write to the live database, `/var/www/places`, the `places-backend` service, or the `/home/john/places-app` checkout.
- New pages and exports follow the PDO Brand & Style Guide summarized in the plan.

Never put secrets, access codes, cookies, or secret-bearing URLs in these documents. Preserve existing entries; add explicit corrections instead of rewriting history. If either document is missing, create a minimal version and record the gap.

## MCP server: three-agent ownership (from 2026-11-17)

The [MCP plan](docs/mcp/PLAN.md) and the [tool contract](docs/mcp/TOOL_CONTRACT.md) govern the MCP server work. Claude Code is the project manager: it writes each task file in `docs/mcp/tasks/`, starts Codex and Antigravity headlessly, reviews their diffs, commits, merges to `beta`, and deploys. Read your task file, the contract, and the files in [docs/mcp/status](docs/mcp/status/) before starting.

- **Claude Code owns** `backend/app/area_pilot/**`, `infra/**`, `docs/mcp/**` (except the other agents' status files), and the handbook.
- **Codex owns** `backend/app/mcp_server/**` and `backend/tests/test_mcp_*`, and later the "Use CHIP with AI" page under `frontend/**`. Its status file is `docs/mcp/status/codex.md`.
- **Antigravity owns** `backend/tests/mcp_eval/**`, `deliverables/mcp/**`, and `docs/mcp/status/antigravity.md`. It works in `/home/john/chip-agy`.
- Codex and Antigravity **do not commit, push, merge, deploy, or use sudo**. They leave their changes uncommitted in their own worktree, update their status file, and stop. Claude commits after review.
- The MCP server reads data only through `app.area_pilot.lookup`, `app.routers.search.search_counties`, and `app/community/topics.json`. It writes nothing. AHRF is not exposed.
- Headless runs record their diary facts in the status file. Claude adds the diary entry when it commits.

## Historical periods: three-agent ownership (from 2026-11-17)

The [history plan](docs/history/PLAN.md) and [source specification](docs/history/SOURCES.md) govern the work that adds earlier periods to the `/area/*` maps and the MCP server. Claude manages it as for the MCP server: it writes task files in `docs/history/tasks/`, dispatches Codex and Antigravity with `chip-dispatch`, reviews, commits, merges to `beta`, and deploys staging. Read your task file and the files in [docs/history/status](docs/history/status/) first.

- **Claude Code owns** everything under `backend/app/area_pilot/**` except the parser paths below, `backend/alembic/**`, `infra/**`, `docs/history/**` (except the other agents' status files), and the handbook. Claude runs every ingest and publication.
- **Antigravity owns** `backend/app/area_pilot/history/parsers/**`, `backend/tests/test_history_parsers_*`, and `docs/history/status/antigravity.md`, as well as its MCP evaluation paths. Its parsers read only source files that Claude has archived and fixtures that Claude provides; they make no network calls and write no database rows.
- **Codex owns** `frontend/**`, `backend/app/mcp_server/**`, `backend/tests/test_mcp_*`, and `docs/history/status/codex.md`.
- County, state, and district profiles must not change: `backend/app/community/**` keeps calling the current-period lookup functions, and the `docs/beta/contract-examples` snapshots stay byte-identical.
- The MCP rules above still apply. Codex and Antigravity do not commit, push, merge, deploy, or use sudo. AHRF history is not exposed by the MCP server.

## CDC NOFO recipient profiles: three-agent ownership (from 2026-11-18)

The [funding MCP plan](docs/funding-mcp/PLAN.md) and Amendment 3 of the [tool contract](docs/mcp/TOOL_CONTRACT.md) govern the NOFO recipient-profile work: the funding MCP tools and the claude.ai skill. Claude manages it as it does the MCP server work. It writes the task files in `docs/funding-mcp/tasks/`, dispatches the other agents with `chip-dispatch`, reviews their work, commits, merges to `beta`, and deploys. Read your task file and the files in [docs/funding-mcp/status](docs/funding-mcp/status/) first.

- **Claude Code owns** `backend/alembic/**`, `infra/**`, `backend/scripts/fetch_usaspending_cdc_award_files.py`, `docs/funding-mcp/**` (except the other agents' status files), `skills/*/SKILL.md`, `skills/*/references/**`, `skills/build_skill_zip.sh`, and the handbook. Claude runs every ingest and every `funding_report` build on live data; Codex may run the build against `places_staging` while developing.
- **Codex owns** `backend/app/funding_report/**`, `backend/app/mcp_server/**`, `backend/tests/test_funding_report_*`, `backend/tests/test_mcp_*`, `skills/*/scripts/**`, `skills/*/assets/**`, `skills/*/tests/**`, and `docs/funding-mcp/status/codex.md`. Codex works in `/home/john/chip-codex-funding`.
- **Antigravity** works in `/home/john/chip-agy-funding` and **owns** the funding questions in `backend/tests/mcp_eval/**`, `deliverables/funding-mcp/**`, and `docs/funding-mcp/status/antigravity.md`.
- The `funding_report` builder reads the source tables and writes only to `funding_report`. The MCP server reads funding only through `app.funding_report.lookup`.
- The MCP rules above still apply. Codex and Antigravity do not commit, push, merge, deploy, or use sudo.


## Profile charts and trends: three-agent ownership (from 2026-11-19)

The [profile chart plan](docs/profile-viz/PLAN.md) and the [chart contract](docs/profile-viz/CHART_CONTRACT.md) govern the charts and trends on county, state, and district profiles. Claude manages it as it does the MCP server work. It writes the task files in `docs/profile-viz/tasks/`, dispatches the other agents with `chip-dispatch`, reviews their work, commits, merges to `beta`, and deploys. Read your task file and the files in [docs/profile-viz/status](docs/profile-viz/status/) first.

- **Claude Code owns** `backend/app/area_pilot/**` (except the parser path below), `backend/alembic/**`, `infra/**`, `docs/profile-viz/**` (except the other agents' status files), and the handbook. Claude runs every ingest and publication.
- **Codex owns** `backend/app/community/**`, `frontend/**`, `backend/tests/test_community_charts_*`, and `docs/profile-viz/status/codex.md`. Codex works in `/home/john/chip-codex-viz`.
- **Antigravity owns** `backend/app/area_pilot/history/parsers/cms_gv.py`, `backend/tests/test_history_parsers_cms_gv*`, `backend/tests/test_profile_charts_audit.py`, `deliverables/profile-viz/**`, and `docs/profile-viz/status/antigravity.md`. It works in `/home/john/chip-agy-viz`.
- **Reassigned 2026-11-19 by John** (Codex is low on usage credits): from task V7 on, Antigravity also owns `backend/app/community/**`, `frontend/**`, and `backend/tests/test_community_charts_*` for this package, in `/home/john/chip-agy-viz`. Codex does not edit them until Claude records the reassignment as ended. **Ended 2026-11-19 (Claude, at John's direction):** Codex is available again and owns these paths as before; the profile-viz package is complete.
- This amends the historical-periods rule for profiles. Existing profile endpoints keep calling only the current-period lookup functions, and the `docs/beta/contract-examples` snapshots stay byte-identical. Profiles may read earlier periods and national values only through the new `/charts` and `/peers` endpoints.
- Charts compute no ranks, changes, or composites, and put values on a shared axis only where the contract's comparability rules allow it. PLACES values are never placed on an axis with BRFSS values.
- The MCP rules above still apply. Codex and Antigravity do not commit, push, merge, deploy, or use sudo.

## CDC state funding profiles: three-agent ownership (from 2026-11-19)

The [state funding plan](docs/state-funding/PLAN.md) and [contract](docs/state-funding/CONTRACT.md) govern the rebuilt page at `/cdc-funding/state/{code}` and its `state_funding` read model. Claude manages it as it does the MCP server work: task files in `docs/state-funding/tasks/`, dispatch with `chip-dispatch`, review, commit, merge to `beta`, and deploy. Read your task file and the files in [docs/state-funding/status](docs/state-funding/status/) first.

- **Claude Code owns** `backend/alembic/**`, `infra/**`, `docs/state-funding/**` (except the other agents' status files), `backend/scripts/fetch_grants_gov_cdc_titles.py`, and the handbook. Claude runs every live build and the title load.
- **Codex owns** `backend/app/state_funding/**`, `backend/tests/test_state_funding_*` (except the audit file), `frontend/**`, and `docs/state-funding/status/codex.md`. Codex works in `/home/john/chip-codex-state` and may run the builder against `places_staging` only.
- **Antigravity owns** `backend/tests/test_state_funding_audit.py`, `deliverables/state-funding/**`, and `docs/state-funding/status/antigravity.md`. It works in `/home/john/chip-agy-state`.
- Supplemental means the File C Disaster Emergency Fund Code split of dollars, never an inferred label. Amounts are not allocated, rescaled, or summed with sub-awards.
- The MCP rules above still apply. Codex and Antigravity do not commit, push, merge, deploy, or use sudo.

## CDC grant history and state funding MCP tools: three-agent ownership (from 2026-11-20)

The [grant history plan](docs/grant-history/PLAN.md), its [contract](docs/grant-history/CONTRACT.md), and Amendment 4 of the [tool contract](docs/mcp/TOOL_CONTRACT.md) govern the page at `/cdc-funding/grant/{nofo}` and the MCP tools `get_state_funding`, `list_state_grants`, and `get_grant_history`. Claude manages it as it does the MCP server work: task files in `docs/grant-history/tasks/`, dispatch with `chip-dispatch`, review, commit, merge to `beta`, and deploy. Read your task file and the files in [docs/grant-history/status](docs/grant-history/status/) first.

- **Claude Code owns** `docs/grant-history/**` (except the other agents' status files), `docs/mcp/TOOL_CONTRACT.md`, `backend/alembic/**`, `infra/**`, and the handbook.
- **Codex owns** `backend/app/state_funding/**`, read-only additions to `backend/app/funding_report/lookup.py`, `backend/app/mcp_server/**`, `backend/tests/test_state_funding_*` and `backend/tests/test_grant_history_*` (except the audit files), `backend/tests/test_mcp_*`, `frontend/**`, and `docs/grant-history/status/codex.md`. Codex works in `/home/john/chip-codex-state`.
- **Antigravity owns** `backend/tests/test_grant_history_audit.py`, the state funding questions in `backend/tests/mcp_eval/**`, `deliverables/grant-history/**`, and `docs/grant-history/status/antigravity.md`. It works in `/home/john/chip-agy-state`.
- No new table or build: the page and tools read the active `state_funding` and `funding_report` builds. Other federal awards are not shown on the grant page.
- The MCP rules above still apply. Codex and Antigravity do not commit, push, merge, deploy, or use sudo.

## CDC state funding map: three-agent ownership (from 2026-11-20)

The [state map plan](docs/state-map/PLAN.md) and [contract](docs/state-map/CONTRACT.md) govern the national map at `/cdc-funding/map`. Claude manages it as it does the MCP server work: task files in `docs/state-map/tasks/`, dispatch with `chip-dispatch`, review, commit, merge to `beta`, and deploy. Read your task file and the files in [docs/state-map/status](docs/state-map/status/) first.

- **Claude Code owns** `docs/state-map/**` (except the other agents' status files), `backend/alembic/**`, `infra/**`, and the handbook.
- **Codex owns** `backend/app/state_funding/**`, `backend/tests/test_state_map_*` and `backend/tests/test_state_funding_*` (except the audit files), `frontend/**`, and `docs/state-map/status/codex.md`. Codex works in `/home/john/chip-codex-state`.
- **Antigravity owns** `backend/tests/test_state_map_audit.py`, `deliverables/state-map/**`, and `docs/state-map/status/antigravity.md`. It works in `/home/john/chip-agy-state`.
- No new table, build, or migration: the map reads the active `state_funding` build, and state outlines only through `app.area_pilot.lookup.area_info`.
- The MCP rules above still apply. Codex and Antigravity do not commit, push, merge, deploy, or use sudo.
