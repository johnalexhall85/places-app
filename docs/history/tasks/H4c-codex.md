# Task H4c (Codex): legend colour note from the API

Branch `codex/history`, owned paths `frontend/**` and `docs/history/status/codex.md`. Same rules as H4: do not commit, push, merge, deploy, or use sudo. Your working tree's `Places2025Pilot.jsx`, its test, and your status file already equal Claude's branch `claude/history-h0`; edit them in place.

**Problem.** For an earlier year, the legend's history notes always print "Colour classes are for this year only; compare values, not colours." (`Places2025Pilot.jsx`, inside `.pilot-history-notes`). That is true only for maps whose classes are recomputed per year (PLACES, ACS income, AHRF, CLH). Fixed-break maps (CMS GV, EPA AQI, USDA FEA, BRFSS, ACS community) use the same cut-points every year.

**API (already deployed on staging).** The history `/legend` response now has `colour_note`:
- fixed breaks: "Colour classes use the same fixed cut-points in every year. Where the note reports a boundary or method change, compare with care."
- per-year classes: "Colour classes are computed for this year only. The same colour can mean a different value in another year, so compare values, not colours."

**Change.**
1. Render `legend.colour_note` in place of the hard-coded sentence when the legend has loaded. Until then, render nothing for that line (do not show a guess).
2. Update the two existing tests (around lines 836 and 854 of `Places2025Pilot.test.jsx`): one with a fixed-break legend mock and one with a per-year mock, each asserting its own sentence; keep the test that the line is absent for the latest year.

Run `npm test` and `npm run build`, add an H4c row with diary facts to your status file, and report in three lines or fewer.
