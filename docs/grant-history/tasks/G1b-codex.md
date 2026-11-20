# Task G1b (Codex): grant history page fixes after Claude's staging review

Assigned by Claude on 2026-11-20. This task uses the same worktree (`/home/john/chip-codex-state`), branch (`codex/grant-history`, now at `706216f`, which Claude committed), ownership, and rules as [G1G2-codex.md](G1G2-codex.md).

The rules repeat here:
- Do not commit.
- Never edit the diary or the handbook.
- Write normally formatted source.

Claude reviewed `/cdc-funding/grant/CDC-RFA-PS21-2102` on staging at 1280 px and 375 px.

## Defects to fix

1. **Expanded row layout (major).**
   - **Problem:** the details render inside the Recipient cell. That squeezes the other columns: the header wraps letter by letter ("FY 20 26 obl iga tio ns") and the amounts wrap ("$1 10, 41 7").
   - **Fix:** render details in a separate full-width row (`<tr><td colSpan=…>`) under the award row, as `CdcStateFundingProfile` does.
   - **Wrapping:** the amount column and its header use `white-space: nowrap`.
   - **Column widths:** give Recipient, Recipient type, and Project title sensible minimum widths, so Recipient type does not break mid-word ("Recip ient").
2. **Phone layout.** At 375 px the table header leaves a large blank area. Use the state page's approach: either the table scrolls inside its own container, or rows stack as cards under 640 px. The page itself must not scroll sideways.
3. **Raw codes shown to users.** Map these to plain labels, as the state page does for `name_source`:
   - `recipient_type_source`: `taggs_recipient_class` → "HHS TAGGS recipient class", `usaspending_business_types` → "USAspending business types", `none` → no label.
   - The district source: `usaspending_current` → "USAspending, current district", `usaspending_original` → "USAspending, district at award", `taggs` → "HHS TAGGS".
   - `abstract_source`, if shown, follows the same pattern.
4. **Expanded details are run-on paragraphs joined with "·".** Use a two-column definition list (a `<dl>` grid that becomes one column on a phone) for:
   - UEI
   - Address
   - Congressional district
   - Recipient type
   - Organization type
   - Business types
   - Metro status
   - Award ID (with the USAspending link)
   - Assistance listing
   - Funding office
   - Period of performance

   Below the list come the abstract, the history, the categories, and the sub-awards sections. Title-case the uppercase USAspending address and business-type strings for display only. Leave the data as it is.
5. **"Also recorded as CDC-RFA-PS21-2102"** repeats the FON itself. Leave out variants equal to `fon_display`, and the whole line when none remain.
6. **Funding by fiscal year bars** start at the centre even when no value is negative, leaving the left half empty. Put the zero line at the left when every value is ≥ 0. Keep the centred zero only when a negative value exists, scaled so the bars stay readable.
7. **By state list:**
   - **Length:** PS21-2102 lists 34 states before the recipients. Show the top 10 with a "Show all 34 states" button.
   - **Link label:** rename the "State profile" link to "State funding page", so it is clear where it goes.
   - **Alignment:** "$0 1 current" runs together. Put the total and the count in separate aligned columns.

## Done when

- Vitest covers:
  - details rendering in their own row;
  - the source labels;
  - variant de-duplication;
  - left-anchored bars when every value is positive;
  - the top-10 states with "Show all".
- `npm test` and `npm run build` pass. Update `frontend/scripts/beta-walkthrough.mjs` if a locator changed, and run `node --check`.
- Take your own Chromium screenshots at 1280 px and 375 px against the mocked or dev server, with one row expanded. In your status file, confirm that the amount column does not wrap and that the page width at 375 px equals the viewport width.
- Add a G1b row and a `## G1b diary facts — <ISO timestamp with timezone>` section to `docs/grant-history/status/codex.md`.

Finish with a report of 10 lines or fewer.
