# Claude status: historical periods

Updated at the end of each task. Claude reads this file before reviewing.

| Package | State | Branch | Notes |
|---|---|---|---|
| H0 Sources and plan | Done | `claude/history-h0` | [SOURCES.md](../SOURCES.md): every product has earlier periods. PLACES dedupes by data year; CMS, USDA, and older years need 2020 county shapes (old CT counties); ACS 2015–2019 and CLH 2018–2019 need 2010 tracts. |
| H2a CMS GV staging publish | Done | `claude/history-h0` | Antigravity parser reviewed. Staging history release `89e8cb19-e78e-4bb9-9ae7-3a4f65cff629`: 79,840 rows, 2019–2023, 0 unmatched boundaries; 8 spot values equal the CMS CSV; only the `:history` pointer was added. |
| H2b–d staging publish | Done | `claude/history-h0` | USDA `897eca1b` (15,732 rows, 13 counties without a 2020 shape), BRFSS `a1e8b193` (4,488), EPA `1672801a` (24,940, 0 unmatched). Spot values equal sources (USDA full precision). Claude: USDA parser skips the source `N/A` FIPS placeholder rows (as the current adapter does); history values are unbounded numeric. |
