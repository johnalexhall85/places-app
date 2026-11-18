# Task F3 (Codex): skill renderer for the NOFO Recipient Profile

Assigned by Claude on 2026-11-18. Work in `/home/john/chip-codex-funding`, on branch `codex/funding-report`. You own these paths:

- `skills/chip-nofo-recipient-profile/scripts/**`
- `skills/chip-nofo-recipient-profile/assets/**`
- `skills/chip-nofo-recipient-profile/tests/**`
- `docs/funding-mcp/status/codex.md`

Do not commit, deploy, or use sudo. Record your facts in the status file and stop.

**Read first:**

- [docs/funding-mcp/PLAN.md](../PLAN.md): the dataset contract `chip.nofo_recipient_profile.v1`.
- [skills/chip-nofo-recipient-profile/SKILL.md](../../../skills/chip-nofo-recipient-profile/SKILL.md): how Claude runs the script.
- [references/report_spec.md](../../../skills/chip-nofo-recipient-profile/references/report_spec.md): the exact layout and brand tokens. This is the specification.
- The content reference, John's restyled PS21-2102 dossier: `/home/john/places-app/data/cdcfundingprofiles/PS21-2102_Recipient_Dossier.docx` and `.xlsx`. Match its structure and completeness. Do **not** copy its navy/Arial look; use the PDO brand.

## Part A first: F2b fixes from Claude's review of F1+F2 (your paths: `backend/app/funding_report/**`, `backend/app/mcp_server/**`, tests)

1. **`project_title`:** use the TAGGS `award_title` (the most common non-empty value for the award). The reference shows "Birmingham Comprehensive High Impact Prevention Project 2 (B-CHIP2)…". Fall back to the USAspending description text before its first `" - "`, cut to 200 characters. `abstract` stays the longest description.
2. **TAGGS data-through:** `action_issue_date` is null in every row, so use the latest successful `taggs.ingestion_runs` row. Set `data_through` to null, and add `loaded_at` (its `finished_at` date) and `coverage` "FY<min>–FY<max> funding fiscal years". The citation becomes "Source: HHS TAGGS · HHS award actions · FY2021–FY2026 · loaded 2026-11-18". Never print "unknown".
3. **Period labels:** write `FY2026 P12`, not `FY2026P12`, in citations and caveats.
4. **Caveats:** rewrite them as plain sentences, for example "USAspending federal account award data (File C) runs through FY2026 P12; FY2026 is complete." Add a caveat whenever the award-level `data_through` is earlier than the end of the last account fiscal year: "Award-level USAspending data runs through 2026-06-18; CDC awards first made after that date are not yet linked to a funding opportunity, although their obligations appear in the account data." Add the caveat about incomplete fiscal years only when one is incomplete.
5. **Dataset route:** run the database and gzip work in `starlette.concurrency.run_in_threadpool` so the event loop is not blocked.
6. **Rebuild** on `places_staging` after these changes. Rerun the funding and MCP tests and the area `--expected-only` evaluation.

## Part B: the renderer (below)

## Requirements

1. **CLI:** `scripts/render.py --dataset FILE --out DIR [--title TEXT] [--narrative FILE] [--prepared YYYY-MM-DD]`.
   - It writes `<FON>_Recipient_Profile.docx` and `.xlsx` and prints one JSON line with the paths, the recipient count, and the page-relevant counts.
   - **Exit codes:** non-zero, with a clear message, on a wrong `schema_version`, missing keys, or missing libraries. For missing libraries, say `pip install python-docx openpyxl matplotlib`.
   - **Dependencies:** Python 3.10+, `python-docx`, `openpyxl`, `matplotlib`, and the standard library only, because it has to run in the claude.ai sandbox. Split it into modules under `scripts/` if that helps (`docx_report.py`, `xlsx_report.py`, `brand.py`, `text.py`).
   - **Performance:** it must handle 600 recipients in under 60 seconds.
2. **Assets** (copied into `assets/`):
   - `PDO_Report_Template.docx` and `chip-logo-fullcolor-light-small.png`, from `/home/john/places-app/branding/legacy-chip/backend-assets-brand/`.
   - `brand.json`, with the tokens from `report_spec.md`.

   Start the Word document from the template: keep its styles, header, footer, and closing "About the Public Data Observatory" table, and replace the placeholder body. Read the guide PDF in that folder if you need to settle anything the spec doesn't cover.
3. **Word:** every section in `report_spec.md`, in order.
   - The TOC is a field that Word updates on open (set `updateFields`).
   - The fiscal-year chart is a matplotlib PNG in the brand colours, with a source line under it.
   - Heading styles must work in the navigation pane.
   - Tables must not split a header from its first row (repeat the header row, and keep a row on one page).
   - Hyperlinks must be clickable.
   - All numbers are formatted by the script: whole dollars with thousands separators in the text, and an em dash for null values.
   - All prose is deterministic sentences generated from the dataset (see the reference's executive-summary paragraphs for the style). The narrative JSON adds only a "Context" subsection.
4. **Excel:** every sheet in `report_spec.md`.
   - Totals use `SUM` formulas.
   - Hyperlinks are real links.
   - Number formats are numeric, never text.
   - Frozen header, auto-filter, column widths, and the brand header style on every sheet.
5. **Sub-awards:** when `dataset.subawards` is null, there is no sub-award section and no sub-award sheets. When it is present, include the section and both sheets, and the per-profile sub-award line.
6. **Tests:** put these in `skills/chip-nofo-recipient-profile/tests/`. Create a venv at `skills/.venv` (it is gitignored, or add it to `.git/info/exclude`) and install python-docx, openpyxl, matplotlib, and pytest there.
   - Build a small synthetic fixture (3 recipients in 2 states, one with no other awards, null values, and sub-awards) and test both the sub-award and no-sub-award runs.
   - Check the structure: headings, sheet names, that formulas are present, and that no "$0" is printed where the value is null.
   - Once F1 is built on staging, also produce real fixtures: `cd backend && PYTHONPATH=. .venv/bin/python -c "..."` calling `app.funding_report.lookup.nofo_dataset` for `PS212102` (with sub-awards) and `CE232301`. Save them to `/home/john/chip-codex-funding/skills/chip-nofo-recipient-profile/tests/fixtures/` (gitignored if larger than 2 MB), and render both.
7. **Visual check:** convert the PS21-2102 .docx to PDF with LibreOffice headless, if it is installed. Otherwise say that you skipped it. Render pages 1, 2, and one profile page to PNG, and look at them. Fix overflow, wrapping, and orphaned headers. Give the PNG paths in your status file.

Report in eight lines or fewer.
