# CDC grant history pages and state funding MCP tools: plan

Approved by John on 2026-11-20. The contract is [CONTRACT.md](CONTRACT.md); task files are in [tasks/](tasks/), and each agent's status is in [status/](status/). Claude manages the work as it does the MCP server work.

## Goal

1. **Grant history page** at `/cdc-funding/grant/{nofo}`. One page for each CDC funding opportunity (NOFO), with:
   - a summary of the grant at the top;
   - recipients grouped by state, with each state's total for the NOFO's latest funded fiscal year;
   - one row per recipient award, showing the recipient name, recipient type, project title, and latest-year obligation;
   - expandable rows with the recipient's details, its fiscal-year history under this NOFO, and a sub-award summary;
   - a searchable, sortable list.

   It follows the recipient profile reports but leaves out other federal awards. Grant rows on `/cdc-funding/state/{code}` link to it.
2. **MCP tools** for state funding and grant history: `get_state_funding`, `list_state_grants`, and `get_grant_history` ([tool contract Amendment 4](../mcp/TOOL_CONTRACT.md)).

## Decisions with John (2026-11-20)

| Question | Decision |
|---|---|
| What a "grant" is | A CDC NOFO, keyed by `fon_key` (the `nofo_key` rule). One row per award (FAIN) under it. |
| "Latest" fiscal year | The NOFO's **last funded fiscal year**: the most recent FY in which the NOFO's grant awards had a positive net obligation. The page labels it. It is FY2026 for active NOFOs. |
| Which recipients | All recipients ever funded under the NOFO (FY2021–FY2026). Current recipients come first, and past recipients show "—" for the latest year. A toggle hides past recipients. |
| Sub-awards | A summary only for now: the number of sub-awardees, the number of actions, and the reported amount. Plan ahead for a sub-awardee list later (contract §6). |
| MCP | Three tools: state summary, state grant list, and grant history. |
| Other federal awards | Not shown. |
| Autonomy | Act between gates. John approves Gate A (staging tryout of the page and the beta MCP connector) and Gate B (live). |

## Facts checked on `places_staging` (Claude, 2026-11-20)

- **Linkability:** all 5,633 FY2026 in-state grants have a NOFO key, across 504 NOFOs. Every grant NOFO key in `state_funding.award` exists in `funding_report.nofo`, and none is a non-CDC NOFO.
- **Grants without a NOFO number:** 42 grant awards across all years have no `fon_key`. They get no history link.
- **Size:** the largest NOFO has 346 awards over FY2021–FY2026 (`OT202004`). 1,327 NOFOs have grants.
- **Awards in more than one state:** 55 awards have obligation rows in more than one state over the years. The contract's grouping rule keeps the state totals exact.
- **Recipient type:** TAGGS `recipient_class` is filled for about 72% of NOFO awards (for example "State Government", "Non-Profit Private Non-Government Organizations", or "County Government"). The rest fall back to USAspending business types.
- **No migration:** the read model is unchanged. `chip_mcp_ro` already has SELECT on `state_funding` (migrations `e4b8c2f6a9d1` and `f7c3a1d9e5b2`) and on `funding_report`.

## Packages

| WP | Owner | Content | Depends on | Status |
|---|---|---|---|---|
| G0 | Claude | Plan, contract, tool contract Amendment 4, AGENTS.md section, task files, branches | none | done |
| G1 | Codex | Grant history lookup, API, page, state-page links, tests | G0 | done (+ G1b, G6 fixes) |
| G2 | Codex | MCP tools `get_state_funding`, `list_state_grants`, `get_grant_history`, tests | G1 lookup | done |
| G3 | Antigravity | Reconciliation audit, MCP eval questions, walkthrough checklist | G1, G2 | done, 7/7 (+ G6 eval runner) |
| G4 | Claude | Review, commit, PR to `beta`, staging deploy (backend and `chip-mcp-staging`), walkthrough; **Gate A** | G1–G3 | done; Gate A passed 2026-11-20 |
| G5 | Claude | **Gate B**: rollback pair, fast-forward `main`, frontend build, restart `places-backend` and `chip-mcp`, verify, handbook, diary, push | Gate A | done, live 2026-11-20 |

Deferred: a sub-awardee list per award (contract §6).

## Ownership

- **Claude:** `docs/grant-history/**` (except the other agents' status files), `docs/mcp/TOOL_CONTRACT.md`, `backend/alembic/**`, `infra/**`, and the handbook. Claude does every deploy.
- **Codex** works in `/home/john/chip-codex-state` on branch `codex/grant-history`. It owns:
  - `backend/app/state_funding/**`
  - read-only functions added to `backend/app/funding_report/lookup.py` (the builder does not change)
  - `backend/app/mcp_server/**`
  - `backend/tests/test_state_funding_*` and `backend/tests/test_grant_history_*`, except the audit files
  - `backend/tests/test_mcp_*`
  - `frontend/**`
  - `docs/grant-history/status/codex.md`
- **Antigravity** works in `/home/john/chip-agy-state` on branch `agy/grant-history`. It owns:
  - `backend/tests/test_grant_history_audit.py`
  - the state funding questions in `backend/tests/mcp_eval/**`
  - `deliverables/grant-history/**`
  - `docs/grant-history/status/antigravity.md`

Codex and Antigravity do not commit, push, merge, deploy, or use sudo.

## Verification

- Backend tests for state funding, grant history, and MCP pass. Frontend `npm test` and `npm run build` pass. The `docs/beta/contract-examples` snapshots are byte-identical, and the MCP eval keeps its pass count plus the new questions.
- The audit (contract §7) passes on `places_staging`.
- **Spot checks:** PS21-2102 (CDC-RFA-PS21-2102) and one FY2026 NOFO with more than 50 states or jurisdictions. Each state total on the grant page must equal the state page's grants filtered to that NOFO.
- **Staging browser walk:** desktop and 375 px phone width with no horizontal page scroll; search, sort, expand, and the past-recipient toggle; the CSV download; the link from a state-page grant row; an anonymous API request returns 401.
- **Beta MCP connector:** in claude.ai, ask for California's FY2026 CDC grants and for PS21-2102's history by state.
