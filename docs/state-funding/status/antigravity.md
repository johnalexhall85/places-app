# State funding: antigravity status

| Task | State | Notes |
|---|---|---|
| S4 | done 2026-11-19T22:58:08+00:00 | Reconciliation audit (`test_state_funding_audit.py`, 7/7 invariants passed on staging build 7) and FY2026 walkthrough checklist (`deliverables/state-funding/walkthrough.md`) complete; uncommitted and undeployed. |

## S4 diary facts — 2026-11-19T22:58:08+00:00

- **Scope and constraints:** Read-only reconciliation audit and staging walkthrough checklist for `places_staging` active build **7** (`state-funding-v1`, FY2021–FY2026, latest period `FY2026 P12`), incorporating Contract §5 plus Amendments 1 (`by_category` and invariant 7) and 2 (default `award_type=grant` alongside explicit `award_type=all`). No application code edited, no database rows written, no network calls, no commits or deployment.
- **Commands run:**
  - `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_state_funding_audit.py -v` → **7 passed** (12.68 s)
  - `cd backend && DATABASE_URL=postgresql+psycopg://bad:bad@127.0.0.1:1/nonexistent PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_state_funding_audit.py -v` → **7 skipped** (0.28 s; verified clean skip when DB unreachable)
  - `cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_state_funding_audit.py tests/test_state_funding_api.py tests/test_state_funding_build.py -v` → **16 passed** (12.89 s)
  - Read-only SQL/lookup inspection scripts against `places_staging` build 7 to gather national totals, deterministic 10th state, and FY2026 walkthrough figures for CA, TX, WY, DC, and PR.
- **Results per invariant (active build 7 on `places_staging`):**
  - **Invariant 1 (File C reconciliation):** **PASS** — 54 combinations (6 FYs 2021–2026 × 3 `funding_type` × 3 `award_type`, incl. `all` and `'__'`) plus 6 direct unattributed (`'__'`) checks; max difference **`$0.00`**. National totals (`all × all`): FY2021 `$55,796,010,011.86`, FY2022 `$16,270,450,540.76`, FY2023 `$18,654,414,464.47`, FY2024 `$11,590,685,262.42`, FY2025 `$9,032,337,115.97`, FY2026 `$10,217,257,000.89`.
  - **Invariant 2 (National `/cdc-funding` overview match via `get_overview`, scope `all_accounts`):** **PASS** — 36 combinations (FY2023–FY2026 × 3 `funding_type` × 3 `award_type`, incl. `all × all`); max difference **`$0.00`** for every cell (FY2023 `$18,654,414,464.47`, FY2024 `$11,590,685,262.42`, FY2025 `$9,032,337,115.97`, FY2026 `$10,217,257,000.89`).
  - **Invariant 3 (Amendment 1 `summary.totals` = sum(`by_category`) = `grants.sum_total` & `award_count` = `total_rows`):** **PASS** — 10 deterministic states (`CA, TX, NY, GA, WY, VT, DC, PR, AK, IN`; TX is #1 most negative FY2025 supplemental at `−$1,022,606,260.82` and IN is #2 / #1 outside the fixed 9 at `−$305,445,373.52`) × 6 FYs × 6 filter sets (`grant`, `all`, `regular/grant`, `supplemental/grant`, `contract`, `state_government/grant` = 360 state-FY-filter checks); max difference **`$0.00`**.
  - **Invariant 4 (Row-level `regular + supplemental = total` and account/category sums):** **PASS** — 10 states × 6 FYs × (`grant`, `all`) covering **30,153** award-year rows; max difference **`$0.00`** across regular+supplemental, nested accounts, and nested categories.
  - **Invariant 5 (Non-empty `grant_name` and valid `name_source`):** **PASS** — **25,918** awards checked; `0` empty/blank names, `0` invalid sources (`award_description`: 14,743; `grants_gov_nofo_title`: 9,812; `assistance_listing_title`: 927; `cdc_funding_profiles_nofo_title`: 310; `taggs_award_title`: 126).
  - **Invariant 6 (Referential completeness `award` ↔ `obligation`):** **PASS** — `0` orphaned `award` rows and `0` missing `award` keys across all **96,715** obligation rows.
  - **Invariant 7 (Amendment 1 crosswalk coverage and category = sum of accounts):** **PASS** — `0` unmapped `federal_account_symbol` values (45 crosswalk rows across 22 categories), `0` mismatches across **2,103** `by_category` entries in the 10-state × 6-FY `lookup.summary` audit, and `0` mismatches in a whole-build SQL check across all states (incl. `'__'`) and FYs.
- **Defects found:** None in `app/state_funding` reconciliation, lookup, or crosswalk invariants. (Note for walkthrough reviewers: `CdcStateFundingProfile.jsx` does not separately render `summary.notes`, though "About these numbers" explains negative obligations; also USAspending records `STATE GOVERNMENT` on prime transactions for some directly-funded CA/TX local health departments, which `is_state_government` faithfully reflects per Contract §1.2.)
- **Files created/updated:**
  - `backend/tests/test_state_funding_audit.py` (created)
  - `deliverables/state-funding/walkthrough.md` (created)
  - `docs/state-funding/status/antigravity.md` (updated)
- **Next action:** Ready for Claude S5 review, commit, PR to `beta`, staging deploy, and Gate A walkthrough. Handbook and formal project diary updates remain with Claude per AGENTS.md.
