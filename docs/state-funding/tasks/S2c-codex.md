# Task S2c (Codex): page polish after Claude's screenshot review of S2b

Assigned by Claude on 2026-11-19. Same worktree, branch, owned paths, and do-not rules as [S2S3-codex.md](S2S3-codex.md). Claude committed S2b as `4baa2cb`. This is a frontend-only task: do not change the API, the build, or the contract. Antigravity is auditing the backend in parallel.

## Fix

1. **Funding by budget category is too tall.** Each category takes about 125 px, and CA FY2026 is about 2,500 px of chart.
   - Show the Supplemental bar row only when the category's supplemental amount under the current filters is not 0. Do the same for Regular.
   - When a category has exactly one federal account, do not render the "Federal accounts (1)" expander. Instead, show one muted line under the category name: "Federal account 075-0950", with the full source account name as the `title` tooltip.
   - Keep the expander for categories with two or more accounts.
   - Target: about 56 px per single-row category on desktop.
2. **Phone KPI tiles:** the numbers drop to about 14 px at 375 px. Keep them at least 22 px Roboto Slab on phone (the tiles may go one per row). Rename the tile "Supplemental/emergency" to "Supplemental (emergency)" so it wraps at the space, not mid-word.
3. **Grants table:** check that the amount and NOFO columns do not wrap at 1280 px. At 375 px the table scrolls inside its container, as it does now.
4. Update the Vitest tests for 1 and 2. `npm test` and `npm run build` must pass.

## Done when

- The status file has an S2c row and `## S2c diary facts — <ISO timestamp with timezone>`.
- `git status` shows changes only under `frontend/**` and your status file.

Finish with a report of 10 lines or fewer.
