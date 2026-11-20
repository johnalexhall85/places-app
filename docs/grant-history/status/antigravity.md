# Grant history: antigravity status

| Task | State | Notes |
|---|---|---|
| G3 | completed, uncommitted 2026-11-20 | All 7 Contract §7 audit invariants pass on `places_staging` (build 7); 6 MCP eval questions (Q67–Q72) and staging walkthrough checklist written. See runner follow-up note below. |

## G3 diary facts — 2026-11-20T00:56:00+00:00

- **Objective:** Implement the independent Contract §7 reconciliation audit (`backend/tests/test_grant_history_audit.py`), add 6 state funding and grant history MCP eval questions (`Q67`–`Q72`) to `backend/tests/mcp_eval/questions.yaml`, and write the staging walkthrough checklist (`deliverables/grant-history/walkthrough.md`). Read-only against `places_staging` (active `state_funding` build `7` and `funding_report` build `7`); no commits, no database writes, no network calls.
- **Files created / edited (strictly within G3 owned paths):**
  - `backend/tests/test_grant_history_audit.py` (created)
  - `backend/tests/mcp_eval/questions.yaml` (appended `Q67`–`Q72`; `Q01`–`Q66` unchanged)
  - `deliverables/grant-history/walkthrough.md` (created)
  - `docs/grant-history/status/antigravity.md` (updated)
- **Commands run:**
  - `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest -v tests/test_grant_history_audit.py` → **6 passed, 1 skipped** (Invariant 7 cleanly skipped when `mcp` is absent), 3.54 s.
  - `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv-mcp/bin/python -m pytest -v tests/test_grant_history_audit.py` → **7 passed**, 3.80 s.
  - Read-only SQL and in-process `.venv-mcp` verification scripts confirming every expected value in `Q67`–`Q72` and `deliverables/grant-history/walkthrough.md`.
- **Selected §7 audit NOFOs (14 distinct, deterministic on build 7):**
  - Top 10 by FY2026 grant total: `TU240137` ($655,656,715.00), `PS240047` ($575,316,922.00), `IP250007` ($454,562,384.00), `CK240002` ($316,353,645.00), `OE222203` ($265,610,999.00), `DP222202` ($218,113,375.06), `CE230002` ($203,554,484.00), `PW240080` ($163,298,725.75), `PW262600` ($156,000,000.00), `DP202001` ($120,126,657.00).
  - Required fixed NOFOs: `PS212102`, `OT202004`, `NH28CE4`.
  - Most split-state NOFO: 0 NOFOs have an award split across multiple states within a single fiscal year on build 7; falling back to multi-state grant awards across all FYs (`ORDER BY count(*) DESC, sum(n_states) DESC, fon_key ASC`) selects `CK191904` (3 multi-state awards across 2 states each; also `latest_fy = 2023`).
- **Audit invariant results (Contract §7, all 7 PASS within $0.01 tolerance):**
  1. **Invariant 1 (`by_fiscal_year.total` vs SQL):** **PASS** across all 14 NOFOs × 6 FYs (84 per-NOFO checks + 6 combined FY checks; combined totals: FY2021 `$30,755,074,445.78`, FY2022 `$916,108,341.25`, FY2023 `$5,492,611,040.79`, FY2024 `-$283,876,228.43`, FY2025 `$437,817,428.75`, FY2026 `$2,516,456,367.48`; `$0.00` discrepancy).
  2. **Invariant 2 (`totals.latest_fy` == `sum(by_state)` == `sum(current awards)`):** **PASS** for total, regular, and supplemental across all 14 NOFOs (`1,187` current award rows).
  3. **Invariant 3 (`by_state` vs paged `lookup.grants`):** **PASS** across all `679` non-`'__'` `(NOFO, state)` pairs, paging `page_size=100` through every row of `lookup.grants(..., award_type='grant')` and matching `nofo_key(fon)`; both state totals and `current_count` matched with `$0.00` discrepancy.
  4. **Invariant 4 (award `history` & `all_years_total` vs SQL):** **PASS** across `1,362` award rows (`4,626` award-FY history rows) for `regular`, `supplemental`, `total`, and `all_years_total`.
  5. **Invariant 5 (`latest_fy` §1 rule in SQL):** **PASS** across all 14 NOFOs (12 at FY2026, `CK191904` at FY2023, `OT202004` at FY2021; `latest_fy_note` verified `None` for all 14).
  6. **Invariant 6 (award coverage & `split_state` exclusivity):** **PASS** across all 14 NOFOs (`1,362` in-scope awards: `1,187` current, `175` past; 0 missing, 0 extra, 0 duplicated past awards, 0 mismatched `split_state` flags).
  7. **Invariant 7 (MCP vs lookup parity under `.venv-mcp`):** **PASS** for `get_grant_history` (`PS212102`, `OT202004`: identical `latest_fy`, `totals`, `by_fiscal_year`, `by_state`) and `get_state_funding` (`CA`, `TX` FY2026 grants: identical `totals` and `by_category`).
- **MCP eval questions added (`backend/tests/mcp_eval/questions.yaml`, verified against SQL and `.venv-mcp`):**
  - `Q67` (`get_state_funding`): CA FY2026 grants total (`$275,957,458.00`; regular `$393,477,480.14`, supplemental `-$117,520,022.14`, 294 awards, 110 recipients).
  - `Q68` (`get_state_funding`): TX FY2026 grants largest budget category (`HIV` — HIV/AIDS, Viral Hepatitis, STI and TB Prevention, `$72,972,128.39`, 40 awards; uses state name `"Texas"`).
  - `Q69` (`list_state_grants`): CA FY2026 grants matching `CDC-RFA-PS21-2102` (`11` rows, `$1,104,148.00`, first FAIN `NU62PS924674`).
  - `Q70` (`list_state_grants`): CA FY2026 top grant by absolute amount (`NH23IP922612`, `CDC-RFA-IP19-1901`, `-$87,227,926.50`, `total_rows=294`, `sum_total=$275,957,458.00`).
  - `Q71` (`get_grant_history`): `CDC-RFA-PS21-2102` latest FY (`2026`, `$10,166,689.00`, 96 recipients, 34 states) and top state (`TX`, Texas, `$1,214,576.00`, 11 current).
  - `Q72` (`get_grant_history`): `NH28CE4` past-recipient count (`191` rows with `include_past=True` vs `52` with `include_past=False`, `139` past awards / recipients).
- **Defects & follow-up notes for Claude:**
  - **No reconciliation defects** found in Codex's `state_funding` lookup or MCP tools.
  - **Eval runner follow-up (`run_eval.py` & `test_checks.py`):** Per G3's strict file ownership list, `backend/tests/mcp_eval/run_eval.py` and `backend/tests/mcp_eval/test_checks.py` were **not** edited. Currently `run_eval.py` only registers the 11 pre-G2 tools in `ALL_TOOLS` (so `run_eval.py --validate` will flag `get_state_funding`, `list_state_grants`, `get_grant_history` as unknown tools until those 3 tools and their lookup/check handlers are added), and `test_checks.py::test_questions_yaml_validates_offline` asserts `summary["total_questions"] == 66` (now `72`).
  - **Minor frontend sort observation (`CdcGrantHistory.jsx` lines 158–159):** On default load (`sort="state_total"`, `dir="desc"`), `groups` re-sorts `data.by_state` by `(a.state.latest_fy_total || 0)`. On `CDC-RFA-TU-24-0137`, where `'__'` ("State not recorded") has `latest_fy_total = 1268643.0`, `'__'` stays last in the "By state, FY2026" list (`data.by_state`) per Contract §2, but moves up above states with smaller totals in the "Recipients" grouped section (and past-only states with `null` sort as `0` under `asc`). Recorded for review; not modified.
- **Status and next action:** Changes are uncommitted in `/home/john/chip-agy-state` on `agy/grant-history`. Ready for Claude review (G4) and optional follow-up to add `get_state_funding`/`list_state_grants`/`get_grant_history` support to `run_eval.py` and `test_checks.py`.
