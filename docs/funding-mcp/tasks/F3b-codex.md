# Task F3b (Codex): fixes from Claude's review of F2b+F3

Assigned by Claude on 2026-11-18. Same worktree, branch, and owned paths as F3. Your F1–F3 work so far has been committed by Claude. Do not commit, deploy, or use sudo. Record your facts in `docs/funding-mcp/status/codex.md` and stop.

I reviewed `/tmp/chip-nofo-ps/CDC-RFA-PS21-2102_Recipient_Profile.docx` against John's reference `/home/john/places-app/data/cdcfundingprofiles/PS21-2102_Recipient_Dossier.docx`.

## Data (`backend/app/funding_report/`)

1. **Assistance listing per award.** Use the CFDA that carries the largest total `federal_action_obligation` across the award's transactions, breaking ties with the TAGGS `aln`.
   - Today NU62PS924730 (Birmingham AIDS Outreach) shows 93.940. The reference and TAGGS have 93.939.
   - Report how many PS21-2102 awards change.
2. **`abstract`.** Prefer the TAGGS `award_description` when it is non-empty, because that is what the reference prints. It is mixed case and capped at about 460 characters by TAGGS.
   - Otherwise use the USAspending description, with a leading "<project title> - " prefix removed when present.
   - Add `abstract_source` (`taggs` or `usaspending`) to the profile, and `abstract_full` (the longest USAspending text, prefix removed) for the Excel sheet only.
3. **Rebuild on staging and rerun the tests.**

## Renderer (`skills/chip-nofo-recipient-profile/scripts/`)

4. **Display casing.** Add a `display_title()` helper for text that USAspending supplies in ALL CAPS: CFDA titles, office names, the cover program title, and the agency line.
   - Title-case words, but keep acronyms upper case: HIV, AIDS, STD, STI, TB, CDC, HHS, NCHHSTP, U.S., and any token containing digits.
   - Keep short connector words lower case: of, and, for, the, in, to, on, with, a, an, by.
   - Never change recipient names, award numbers, or the abstract.
5. **TAGGS class text.** Normalize spaces inside parentheses: "Private Profit ( Small Business ) Organizations" becomes "Private Profit (Small Business) Organizations".
6. **Dates.** Write ranges as "July 1, 2021 – June 30, 2026", with spaces around the en dash, in prose and in the Word tables. Excel keeps ISO dates as real date cells.
7. **Address.** Write "205 32ND ST S, BIRMINGHAM, AL 35233 (JEFFERSON County)", with no comma between the state and the ZIP.
8. **Headings.** In each profile, the sub-section headings ("<short FON> Award", "Obligations by fiscal year", "Funded project", "Other HHS Awards", "Sub-awards") become Heading 3. Heading 1 stays the state and Heading 2 the recipient. The TOC shows levels 1–2 only.
9. **Funded project text.** Print the abstract as given and append "…" only when you cut it. Add a muted line: "Abstract: TAGGS award description" or "Abstract: USAspending award description".
10. **States.** "Where recipients are located" names the territories (DC, PR, VI, GU, and others) separately from the states, as the reference does: "33 states, the District of Columbia, Puerto Rico, and the U.S. Virgin Islands".
11. **Visual check.** `/usr/bin/soffice` may still be missing. If it is, skip the check and say so.
12. **Rerun everything.** Rerun the renderer tests, render both real fixtures again to `/tmp/chip-nofo-ps` and `/tmp/chip-nofo-ce`, and rerun the funding and MCP tests.

Report in six lines or fewer.
