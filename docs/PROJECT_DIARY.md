# CHIP project diary

Reverse chronological handoff record. Timestamps use ISO 8601 with an explicit timezone. Entries describe verified actions; guide-only history is labeled. Keep current state in [the handbook](PROJECT_HANDBOOK.md), not here. Preserve entries and add corrections when evidence changes.

## 2026-11-14T16:28:50+00:00 — Consolidate approved work onto main

- **Objective/outcome:** User approved committing all pending work and asked for the current branch to become `main` and be pushed. `origin/main` is an ancestor of `claude/improvements`, so a fast-forward is available; commit and push remain pending at this entry's creation.
- **Changes reviewed for commit:** CDC funding API outlay trends and frontend redesign/tests, demo-access session handling and demo startup readiness check, recipient dossier/subawardee report scripts, local recovery helpers, a hypothetical CHIP use-case deck and notes, Claude orientation, and the prior uncommitted diary entry. Updated this handbook for the new code and recovery-helper status. Dataset pointers, migrations, services, timers, storage, and deployed assets were not changed by this task.
- **Verification:** Read the branch and remote history after `git fetch origin`; `origin/main` had zero commits outside current `HEAD`. Focused backend tests passed 50/50 with `PYTHONPATH=. .venv/bin/python -m pytest`; the first direct `.venv/bin/pytest` invocation failed collection because `app` was not on its import path. Frontend tests passed 117/117 and `npm run build` succeeded with a bundle-size warning. Bash syntax, Python compilation, and PowerPoint ZIP integrity checks passed. No data import or destructive recovery command was run. Full backend suite and deployed browser verification were not run.
- **Publication/next action:** Commit all nonignored work, fast-forward local `main`, push `origin/main` without force, then record the final branch and push result. The older local recovery set still predates AHRF/CLH and requires a new isolated restore plus independent copy.

## 2026-11-14T16:24:34+00:00 — Claude Code orientation alongside Codex

- **Objective/outcome:** Read-only orientation for Claude Code. No application code, data, migration, pointer, service, or deployment change. Added root `CLAUDE.md`, which imports `@AGENTS.md` (none existed before), and this entry; both are uncommitted.
- **Verified state:** Host `chip-app`, user `john`, repo `/home/john/places-app`, branch `claude/improvements` at `0b9372b`, level with `origin/claude/improvements`. Uncommitted funding/demo-access edits, `backend/scripts/chip_recovery/`, three other untracked scripts, `backend/docs/chip_phase1_next_codex_prompt.md`, and `deliverables/` were left untouched. Only root `AGENTS.md` exists in-repo; no nested instruction files. Codex app-server was running; Codex also uses its global `~/.codex/AGENTS.md`, which matches this workflow. `places-backend`, Nginx, and `chip-area-refresh.timer` were active.
- **Discrepancy:** Sibling worktree `/home/john/places-app-ahrf-push` holds `codex/ahrf-county-five-measures` (`ec6dddd`). Its two commits are not ancestors of `HEAD`, but AHRF code is on this branch through `89fc4d8`. Treat that branch as superseded unless someone confirms otherwise. This is unverified at the content level.
- **Next action:** Unchanged from the handbook priorities. Commit `CLAUDE.md` with the next authorized documentation commit.

## 2026-11-14T16:11:48+00:00 — Documentation publication handoff

- **Objective/outcome:** Committed the handbook, diary, root `AGENTS.md`, and three supporting operator documents as `0b03cc8`; pushed `claude/improvements` to `origin` successfully without force. The push also carried four pre-existing local commits already ahead of the branch upstream. This follow-up diary record is a separate documentation-only change.
- **Verification:** `git diff --cached --check` passed before the first commit; all handbook and supporting-document local links resolved, and documented Python command targets existed. The push reported `5b4dcda..0b03cc8`. No application tests, deployment, data import, migration, pointer change, or service restart occurred for the documentation task.
- **Next action:** Push this diary follow-up entry, then inspect final branch/working-tree status. A new recovery set and off-host copy, CLH source retry, and the untracked recovery helpers remain separate work.

## 2026-11-14T16:07:50+00:00 — Central documentation and agent workflow

- **Objective/outcome:** Created the canonical handbook and this diary, plus root `AGENTS.md` task-start and handoff rules. No application code, data, release pointer, service, timer, or deployed asset was changed for this request.
- **Files and decisions:** `docs/PROJECT_HANDBOOK.md` records current architecture, per-integration inventory, shared versus legacy/funding boundaries, commands, decisions, and gaps. `docs/PROJECT_DIARY.md` starts the evidence-backed history. `AGENTS.md` requires future agents to read and maintain them. Existing untracked audit, pipeline-plan, and local-recovery guides were included so handbook references resolve in Git; the maintained broader source inventory remains `backend/docs/chip_source_inventory.csv`.
- **Verification:** Inspected repository manifests, registries, migrations, routes, operator guides, and git state. Read-only `area_pilot` queries showed four independent published pointers and DB revision `c9f76d3a51e2`; budget, federal-account, and TAGGS table counts were also read. `app.area_pilot.operations status` showed PLACES/ACS content checks current; `systemctl` showed backend, Nginx, and weekly area timer active/enabled. Local and Nginx health returned 200; anonymous area catalog returned 401. All local Markdown links and documented command target files resolved; the four shared CLI `--help` entry points succeeded. Bare `python` was unavailable in the host shell, so subsequent checks used `python3` or `backend/.venv/bin/python`; a pre-existing `requests` dependency warning appeared. No full ingestion, migration, build, or test suite was run because this is a documentation-only change.
- **Deployment/publication:** No deployment or data publication. Commit and push are pending at this entry's creation.
- **Issue/next action:** Earlier local recovery set predates active AHRF/CLH releases and must be refreshed and copied off-host. Its helper scripts are untracked and unavailable from a clean remote checkout. CLH source re-fetch had held HTTP 202 responses per its guide. Review the staged documentation diff, then commit only intended documentation and push without force. Preserve unrelated working-tree changes.

## 2026-11-14T15:55:10+00:00 — CLH integration milestone (Git evidence)

- **Objective/outcome:** Commit `89fc4d8` adds curated AHRQ CLH to the shared area pipeline. The [CLH guide](../backend/docs/chip_clh_2023_curated.md) reports checksum-bound publication and deployment on November 14, with authenticated browser/API checks and a supervised pointer recovery; the author-time timestamp here is from Git, not the deployment time.
- **Files/data:** `backend/app/area_pilot/clh*`, the CLH registry/migration, shared area routes and UI, and five curated indicators from September 2025 v2.0 files. Live read-only DB inspection at this diary's creation found active CLH release `168ec07d-c7ef-4e46-b01a-ec72c00c3d88` and three held CLH candidates.
- **Issue/next action:** The guide records empty HTTP 202 responses on repeat source fetch; replay of archived workbooks matched published content. Recheck source availability before a new candidate. Existing weekly timer does not include CLH.

## 2026-11-13T23:46:15.861150+00:00 — Shared area releases (ACS publication time from live DB)

- **Objective/outcome:** [PLACES](../backend/docs/chip_places_2025_pilot.md) and [ACS](../backend/docs/chip_acs5_2024_phase3.md) guides report published/deployed releases, release-pinned map/legend/table parity, authenticated browser checks, and pointer recovery. Live DB publication times were 2026-11-13T23:14:56.930499+00:00 for combined PLACES and the heading timestamp for ACS. The [operations guide](../backend/docs/chip_area_phase4_operations.md) records a weekly PLACES/ACS verification timer and supervised full-content checks completed early November 14. These are historical actions, not operations performed for this diary.
- **Files/data:** `area_pilot` releases, 2023/2020 PLACES-compatible boundaries, isolated 2024 ACS boundaries, raw archives, API and React area page. Live pointers were rechecked on November 14; see handbook for current values.
- **Issue/next action:** No automatic publication. Source endpoint/schema drift and archive growth need operator review. The [local recovery guide](../backend/docs/chip_current_recovery_set.md) reports an isolated restore of a pre-AHRF/CLH snapshot; its proposed nightly schedule has not been commissioned.

## 2026-08-22T21:21:41+00:00 — Funding trend code milestone (Git evidence)

- **Objective/outcome:** Commit `ad3a667` added CDC funding trend analysis. Earlier commits `a3de3b1` and `e309a0d` on July 27 added summary outlay backfill and restored the all-account overview; `04efb55` on July 3 added the v1 funding map model. This summary establishes code history only; corresponding deployment dates and full data validation were not reconstructed here.
- **Files/data:** [CDC funding API guide](../backend/docs/cdc_funding_api_v1.md), [source ingestion guide](../backend/docs/cdc_funding_source_ingestion.md), funding database/schema and frontend funding pages. Later uncommitted funding edits were present at this diary's creation and remain outside this documentation task.

## 2026-04-24T14:31:30+00:00 — Demo access and funding base (Git evidence)

- **Objective/outcome:** Commit `ec97672` added demo access and budget-grounded funding; `9b71dd1` later that day added USAspending federal-account ingestion. March 2026 commits introduced CMS, USDA, FEMA, CDC funding, and model components. Dates are commit author times; ingestion/publication completeness for those legacy products is described cautiously in the [November 13 audit](../backend/docs/chip_federal_data_current_state_audit.md).
- **Files/data:** [access middleware](../backend/app/demo_access/middleware.py), funding and legacy importers, migrations, and [scripts guide](../backend/scripts/README.md). The shared area release system did not apply to these earlier integrations.
