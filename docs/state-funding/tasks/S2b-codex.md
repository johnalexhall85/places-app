# Task S2b (Codex): budget categories (contract Amendment 1)

Assigned by Claude on 2026-11-19, after S2+S3. The worktree, branch, owned paths, commands, and do-not rules are the same as in [S2S3-codex.md](S2S3-codex.md). Claude has fast-forwarded your branch to include migration `f7c3a1d9e5b2` (already applied on `places_staging`) and the amended contract. Do not edit migrations.

## Read first

1. [CONTRACT.md](../CONTRACT.md) **Amendment 1** (at the end). It overrides the earlier sections where they differ.
2. `backend/alembic/versions/f7c3a1d9e5b2_add_state_funding_budget_category.py`: the crosswalk rows.
3. Your own S2+S3 work and Claude's review notes, if any are under `## Review` in `docs/state-funding/status/codex.md`.

## Build

1. **Builder:** fail with the missing symbols if any source account in FY2021+ lacks a crosswalk row. Record the crosswalk source and row count in `build_run.sources`. Rebuild on `places_staging`.
2. **Lookup and API:**
   - Add the `category` filter. `account` now returns 422 with a message that names `category`.
   - Replace `by_account` with `by_category` (each with its nested `accounts`), and `accounts_available` with `categories_available`.
   - Grant rows gain `categories[]`; sorting gains `category`; `q` also matches category names.
   - The CSV gains a `categories` column.
3. **Page:**
   - Rename the chart to "Funding by budget category"; each category expands to show its federal accounts.
   - Label categories that are outside the operating plan.
   - Change the filter to "Budget category" and the table column to "Budget category". Federal accounts move into the expanded row.
   - Add the method note from the amendment.
   - The query string uses `category`.
4. **Tests:**
   - Update the backend and frontend tests for the above.
   - Add a test that the build fails on an unmapped account (use a fixture or a temporary table; never delete crosswalk rows on staging).
   - Add a test that `account=` returns 422.
   - Add a test that, for one staging state and fiscal year, each category's total equals the sum of its accounts.

## Done when

- All tests pass, the staging build is rebuilt, and §5.1 still reconciles to the cent.
- The status file has an S2b row and a section `## S2b diary facts — <ISO timestamp with timezone>`.

Finish with a report of 10 lines or fewer.
