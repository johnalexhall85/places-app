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
