# CHIP project diary

Reverse chronological handoff record. Timestamps use ISO 8601 with an explicit timezone. Entries describe verified actions; guide-only history is labeled. Keep current state in [the handbook](PROJECT_HANDBOOK.md), not here. Preserve entries and add corrections when evidence changes.

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
