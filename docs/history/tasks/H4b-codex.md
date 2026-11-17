# Task H4b (Codex): year-aware copy on the area maps

Branch `codex/history`, owned paths `frontend/**` and `docs/history/status/codex.md`. Same rules as H4.

Claude's signed-in staging walkthrough of H4 passed on CMS GV, BRFSS, EPA AQI, and USDA FEA at 1365 px and 375 px. Fix these copy issues, which appear when an earlier year is selected:

1. **USDA FEA bullets.** "Connecticut values exist only for its eight former counties and cannot be shown on the 2024 planning-region boundaries" is only true for the latest year. For an earlier year, Connecticut's former counties are drawn, so say that instead. Also replace "Each measure has its own observation year (2018–2023)" with wording that is true for every year.
2. **Pluralization:** "1 areas published for this year have no matching boundary…" must read "1 area … has" when the count is one.
3. **Hard-coded years and boundaries.** Search `Places2025Pilot.jsx` for any remaining year or boundary text that describes only the latest year in the scope text, bullets, and status legends (for example "2024 boundary", "2025", "2023", "TIGER/Line 2024"). Make each one follow the selected period's `boundary_vintage` and `period`, or limit it to the latest year.

Add or extend tests, run `npm test` and `npm run build`, add an H4b row with diary facts to your status file, and report in three lines or fewer.
