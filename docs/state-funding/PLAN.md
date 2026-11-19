# CDC state funding profiles: plan

Approved by John on 2026-11-19. The contract is [CONTRACT.md](CONTRACT.md); task files are in [tasks/](tasks/), and each agent's status is in [status/](status/). Claude manages the work as it does the MCP server work.

## Goal

Replace the page at `/cdc-funding/state/{code}` with a page that follows the PDO brand. It shows:
- how much CDC money went to recipients in a state in one fiscal year;
- regular and supplemental dollars, split without inference;
- the money by federal account;
- a searchable list of grants with name, description, and amount.

Filters match the `/cdc-funding` Filters panel. A history page for each grant comes later.

## Decisions with John (2026-11-19)

| Question | Decision |
|---|---|
| Which recipients count | All recipients whose `recipient_state` is the state. A Recipient type filter (All / State government) uses the USAspending business types, as the source states them. |
| Supplemental | A **dollar** split by File C Disaster Emergency Fund Code: Q or blank is regular, any other code is supplemental/emergency. This is the `emergency` column that the `/cdc-funding` Funding type filter uses. One grant can hold both kinds. Award *actions* are not labelled, because no source states it. |
| Years | One fiscal year at a time, FY2021–FY2026. The default is the latest complete year. |
| Filters | Funding type, Award type, Federal account (as on `/cdc-funding`), plus Recipient type and grant search. |
| Grant name | The NOFO title, matched exactly on the funding opportunity number. If there is none, the TAGGS award title, then the assistance listing title. The page shows where each name came from. |
| Old page | Replaced in place at the same URL. Old query parameters are ignored, and the old code stays in git. |
| Agents | Codex builds `app/state_funding` and the page. Antigravity writes the reconciliation audit and the walkthrough. Claude writes the plan, contract, migration, and title ingest, then reviews, merges, deploys, and runs every live build. |
| Autonomy | Act between gates. John approves Gate A (staging tryout) and Gate B (live). |
| Profile-viz reassignment | Ended 2026-11-19. Codex owns `frontend/**` again. |

## Facts checked on `places_staging` (Claude, 2026-11-19)

- `cdc_funding.cdc_funding_awards` FY totals equal `cdc_funding_account_annual` (the `/cdc-funding` source) to the cent for FY2020–FY2026.
- The `emergency` column comes from DEFC: Q or blank gives NonEmergency; L, N, P, U, V, 6, AAB, E, C, X, and 2 give Emergency.
- Emergency dollars are **net negative** nationally in FY2024 (−$2.25B), FY2025 (−$3.21B), and FY2026 (−$2.30B), because COVID-era money is being deobligated.
- Blank `recipient_state` holds $155M–$405M a year. It is shown as Unattributed in the audit, not on any state page.
- For FY2026 in-state grants (5,633 awards): every award has a funding opportunity number (from USAspending or TAGGS), across 505 distinct numbers. 99.5% have a TAGGS award title. The CDC Funding Profiles reference has a NOFO title for only about 5% of awards, so Grants.gov titles are needed.
- About 27% of FY2026 in-state awards have a USAspending business type that contains "STATE GOVERNMENT".

## Packages

| WP | Owner | Content | Depends on | Status |
|---|---|---|---|---|
| S0 | Claude | Plan, contract, task files, AGENTS.md section, worktrees; migration `e4b8c2f6a9d1` (applied on staging) | none | done |
| S1 | Claude | Grants.gov title extract archived and loaded into `state_funding.nofo_title` on staging, with CDC Funding Profiles titles; coverage report | S0 | |
| S2 | Codex | `app/state_funding` builder, lookup, router, tests | S0 (titles optional at build) | |
| S3 | Codex | New page, tests, removal of the old page | S2 | |
| S4 | Antigravity | Reconciliation audit test and walkthrough checklist | S2 | |
| S5 | Claude | Review, commit, PR to `beta`, staging build and deploy, audit and walkthrough; **Gate A** | S3, S4 | |
| S6 | Claude | **Gate B**: rollback pair, live migration, title load, `build --allow-live`, deploy, verify, handbook, diary | Gate A | |

Deferred: a grant-history page per award or NOFO; MCP tools for state funding; an operating-plan crosswalk.

## Ownership

- **Claude:**
  - `backend/alembic/**`, `infra/**`, `docs/state-funding/**` (except the other agents' status files), and the handbook
  - `backend/scripts/fetch_grants_gov_cdc_titles.py`
  - every live build
- **Codex** (`/home/john/chip-codex-state`, branch `codex/state-funding`):
  - `backend/app/state_funding/**`
  - `backend/tests/test_state_funding_*` (except the audit file)
  - `frontend/**`
  - `docs/state-funding/status/codex.md`
- **Antigravity** (`/home/john/chip-agy-state`, branch `agy/state-funding`):
  - `backend/tests/test_state_funding_audit.py`
  - `deliverables/state-funding/**`
  - `docs/state-funding/status/antigravity.md`

Codex and Antigravity do not commit, push, merge, deploy, or use sudo.

## Verification

- `pytest backend/tests/test_state_funding_*` passes, and the audit passes on `places_staging` for every FY and filter combination.
- Frontend `npm test` and `npm run build` pass. The `docs/beta/contract-examples` snapshots are byte-identical, and the MCP eval keeps its pass count.
- **Spot checks:**
  - For three states, the page total equals the SQL sum by `recipient_state`.
  - Five grants are checked against USAspending.gov.
  - Search finds a grant by FAIN, by NOFO number, and by a word in its description.
- **Staging browser walk:**
  - desktop and phone width, with no horizontal scroll;
  - filters and chips;
  - CSV download;
  - the link from the community state profile;
  - an anonymous request returns 401.
