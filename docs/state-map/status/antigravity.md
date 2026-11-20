# Antigravity status: state funding map

## Task M2b — Invariant 4 after Amendment 2 & FY2023 Palau walkthrough step (2026-11-20T15:08:00Z)

- **Status:** Complete — all **6/6** audit tests pass on `places_staging` (CHIP build 7, `state-funding-v1`).
- **Branch / worktree:** `agy/state-map` in `/home/john/chip-agy-state` (uncommitted; owned paths only).
- **Files updated:**
  - `backend/tests/test_state_map_audit.py` — updated `ALLOWED_NO_SHAPE_CODES` and docstrings per Contract Amendment 2 to allow `{"GU", "VI", "AS", "MP", "FM", "MH", "PW"}`.
  - `deliverables/state-map/walkthrough.md` — added the FY2023 Palau (`PW`) tile step under Section 7 (9-tile order `DC, PR, GU, VI, AS, MP, FM, MH, PW`, hover tooltip, click panel figures `$13,098,676` / `$2,676,004` regular / `$10,422,672` supplemental / 17 grants / 1 recipient, top 5 budget categories, `/cdc-funding/state/PW?fy=2023&funding_type=all&award_type=grant`, omitted State indicators link) and noted Amendment 2 tile-hiding and legend-bound merging.
  - `docs/state-map/status/antigravity.md`
- **Audit rerun (`places_staging`, CHIP build 7):**
  ```bash
  cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_state_map_audit.py -v
  ```
  Outcome: **6 passed, 0 failed** (46.54s):
  - `test_map_shapes_contract` — **PASS**
  - `test_invariant_1_totals_reconcile_to_national_and_sql` (48 slices) — **PASS** (largest diff `$0.00`)
  - `test_invariant_2_sampled_states_match_summary_endpoint` (460 present + 25 absent state-slice checks) — **PASS** (largest diff `$0.00`)
  - `test_invariant_3_regular_plus_supplemental_equals_total_and_non_negative_exclude` (2,644 rows) — **PASS** (largest diff `$0.00`)
  - `test_invariant_4_shapes_and_non_shape_territory_codes` (1,445 standard rows across FY2021–FY2026; `FM`, `MH`, `PW` now allowed with `has_shape=false` and `indicators_geoid=null`) — **PASS** (0 violations)
  - `test_invariant_5_no_zero_award_count_state_rows` (2,644 rows) — **PASS**
- **Open questions:** None.

---

## Task M2 — State funding map audit and walkthrough checklist (2026-11-20T15:03:00Z)

- **Status:** Complete (1 contract invariant failure found and documented below; awaiting Claude review/decision on `FM`/`MH`/`PW`).
- **Branch / worktree:** `agy/state-map` in `/home/john/chip-agy-state` (uncommitted; `backend/app/state_funding/*` left untouched as copied by Claude).
- **Files written (owned paths only):**
  - `backend/tests/test_state_map_audit.py`
  - `deliverables/state-map/walkthrough.md`
  - `docs/state-map/status/antigravity.md`

### Audit run & results (`places_staging`, CHIP build 7, `state-funding-v1`, FY2021–FY2026)

Command run:
```bash
cd backend && PYTHONPATH=. /home/john/chip-claude/backend/.venv/bin/python -m pytest tests/test_state_map_audit.py -v
```

Outcome: **5 passed, 1 failed** (6 tests across **48** API slices: 27 standard `deobligations=include` slices = 6 FYs × 3 funding types + 3 FY2026 categories `HIV`/`CROSS`/`PHPR` × 3 funding types; plus 21 Amendment 1 `deobligations=exclude` slices = 6 FYs × 3 funding types + 3 FY2026 categories `HIV`/`CROSS`/`PHPR` with `funding_type=all`).

- **Total reconciliation checks:**
  - Contract §2 `/map/shapes`: **1** check (52 shapes, `TIGER/Line 2024`, `Cache-Control: public, max-age=86400`, 140,796 bytes < 400 KB) — **PASS**
  - **Invariant 1** (`states[].total` sum + `unattributed.total` == `national.total` == direct SQL `state_funding.obligation` sum, plus award counts, `< 60 KB` payload [FY2026 default 14,633 bytes], notes, and `deobligations=exclude` non-negativity): **48** slices — **PASS**, largest dollar diff **`$0.00`**
  - **Invariant 2** (10 sampled states `CA, TX, NY, GA, WY, VT, DC, PR, AK, GU`, topped up to `min(10, len(states))` in sparse slices, vs. `GET /state-funding/v1/states/{code}/summary?award_type=grant`): **460** present state-slice reconciliations (+ **25** absent-state zero/422 verifications) — **PASS**, largest dollar diff **`$0.00`**
  - **Invariant 3** (`regular + supplemental == total`, opposite funding type zeroed, and `total, regular, supplemental >= 0` under `deobligations=exclude`): **2,644** state rows — **PASS**, largest dollar diff **`$0.00`**
  - **Invariant 4** (`has_shape=true` in `/map/shapes`, `indicators_geoid` matches `area_lookup.states`, and `has_shape=false` restricted to `{GU, VI, AS, MP}`): **1,445** standard state rows — **FAIL** (**45** violations in FY2021–FY2025; **0** violations in FY2026; **0** missing shapes; **0** `indicators_geoid` mismatches)
  - **Invariant 5** (`award_count > 0`, `recipient_count > 0`, sorted by `name`, no `'__'` in `states[]`): **2,644** state rows — **PASS**
- **Overall largest dollar difference** across all **3,152** dollar comparisons (48 Inv 1 slices + 460 Inv 2 state-slices + 2,644 Inv 3 rows): **`$0.00`**.
- **Unreachable-DB skip verification:** Verified `test_state_map_audit.py` skips cleanly (6 skipped, 0 failed) when `DATABASE_URL` is unreachable.

### Failing invariant details — Contract §5 Invariant 4 (`FM`, `MH`, `PW` in FY2021–FY2025)

Contract §5 Invariant 4 states: *"Every code with `has_shape = false` is GU, VI, AS, or MP, and every code with `has_shape = true` is in `/map/shapes`."*

In **FY2026**, only `AS`, `GU`, `MP`, and `VI` have `has_shape = false` (56 rows in `states[]`, passing Invariant 4). However, in **FY2021–FY2025**, `state_funding.obligation` also has grant rows for the three Freely Associated States — **`FM`** (Federated States of Micronesia), **`MH`** (Marshall Islands), and **`PW`** (Palau) — producing **59** rows in `states[]` with `has_shape = false`, `fips = null`, and `indicators_geoid = null` across all 15 non-FY2026 standard slices (5 FYs × 3 funding types = **45** occurrences):

| FY | `FM` (all / reg / sup; awards) | `MH` (all / reg / sup; awards) | `PW` (all / reg / sup; awards) |
|---|---|---|---|
| FY2021 | `$19,018,838.12` (`$2,706,197.12` / `$16,312,641.00`; 15) | `$14,757,231.88` (`$1,404,250.88` / `$13,352,981.00`; 16) | `$9,561,060.90` (`$1,905,938.90` / `$7,655,122.00`; 16) |
| FY2022 | `$3,227,825.07` (`$2,691,401.07` / `$536,424.00`; 17) | `$4,362,053.17` (`$3,256,965.17` / `$1,105,088.00`; 17) | `$2,983,381.85` (`$2,094,376.85` / `$889,005.00`; 15) |
| FY2023 | `$15,273,561.59` (`$3,818,273.59` / `$11,455,288.00`; 16) | `$7,438,354.90` (`$2,647,639.90` / `$4,790,715.00`; 14) | `$13,098,676.05` (`$2,676,004.05` / `$10,422,672.00`; 17) |
| FY2024 | `$6,032,717.51` (`$4,553,705.00` / `$1,479,012.51`; 15) | `$2,358,276.73` (`$2,965,923.00` / `−$607,646.27`; 15) | `$4,897,827.89` (`$3,464,099.00` / `$1,433,728.89`; 18) |
| FY2025 | `$3,607.54` (`$4,769,486.44` / `−$4,765,878.90`; 19) | `$5,040,394.33` (`$3,901,792.00` / `$1,138,602.33`; 18) | `$3,466,368.16` (`$3,848,569.76` / `−$382,201.60`; 20) |
| FY2026 | *(none)* | *(none)* | *(none)* |

Note: `/state-funding/v1/states/{FM,MH,PW}/summary` already serves these three codes validly in FY2021–FY2025, so they reconcile cleanly with Invariants 1, 2, 3, and 5; the mismatch is strictly against Contract §3 (tiles only for `DC, PR, GU, VI, AS, MP`) and Contract §5 Invariant 4.

### Open questions for Claude

1. **Freely Associated States (`FM`, `MH`, `PW`) in FY2021–FY2025:** Should Contract §3 and §5 Invariant 4 be amended to include `FM`, `MH`, and `PW` (for example, adding tiles for them when present or explicitly documenting them as table-only non-shape areas, and expanding `ALLOWED_NO_SHAPE_CODES` to `{GU, VI, AS, MP, FM, MH, PW}`), or should `state_map.py` keep them out of `states[]` (e.g., separate note/bucket)? Note that rolling them into `unattributed` would diverge from the `'__'` definition, whereas adding conditional tiles or amending Invariant 4 preserves exact state-page parity (`/cdc-funding/state/FM`, `/MH`, `/PW`).
2. **Walkthrough checklist:** Written to `deliverables/state-map/walkthrough.md` with verified `places_staging` build 7 figures for all requested controls, Amendment 1 (`deobligations=exclude`), tooltips, California panel + both links, Georgia negative state, DC and Guam tiles, table sorting, and 375 px phone width.
