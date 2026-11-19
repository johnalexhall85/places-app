# State funding: claude status

| Task | State | Notes |
|---|---|---|
| S0 | done 2026-11-19 | Plan, contract, task file, worktrees; migration `e4b8c2f6a9d1` applied on `places_staging` only. |
| S1 | done 2026-11-19 | `state_funding.nofo_title` loaded on `places_staging`: 23,927 Grants.gov titles (HHS agency codes) and 569 CDC Funding Profiles titles. |

## S1 facts — 2026-11-19 (UTC)

- **Extract:** `GrantsDBExtract20261119v2.zip`, SHA-256 `38e820b50d8cdbcdc12841e9784286ee62464ce49a26c5973a5d77737237f0e2`, archived at `data/grantsgov/20261119/` in `/home/john/chip-claude`. It must be copied to the live checkout's `data/` at Gate B.
- **Load command:** `cd backend && python scripts/fetch_grants_gov_cdc_titles.py --zip ../data/grantsgov/20261119/GrantsDBExtract20261119v2.zip --apply` (staging; live needs `--allow-live`).
- **Agency scope:** the load takes all HHS agency codes, not CDC only. CDC funds grants under NIH-posted parent announcements (for example PA-21-259 and RFA-OH-22-003). Opportunity numbers are unique in Grants.gov, and a CDC record wins on any repeat.
- **Share of in-state grants with a NOFO title**, Grants.gov / either source:
  | FY | Grants.gov | Either source |
  |---|---|---|
  | FY2021 | 82.4% | 90.8% |
  | FY2022 | 84.7% | 92.1% |
  | FY2023 | 88.4% | 96.3% |
  | FY2024 | 93.0% | 98.5% |
  | FY2025 | 93.5% | 99.1% |
  | FY2026 | 94.7% | 99.0% |
- **Grants still unmatched** fall back to TAGGS titles. They are mostly CDC-internal numbers with no public opportunity (`NH28CE4`, `TO-NB01TO-23-001`, `OT-NB01OT-22-001`).
- **Title differences:** CDC Funding Profiles titles are sometimes component-specific (PS21-2102 gives "Transgender Status-Neutral…", where Grants.gov gives "Comprehensive High-Impact HIV Prevention Programs for Community-Based Organizations"). Grants.gov therefore ranks first.
