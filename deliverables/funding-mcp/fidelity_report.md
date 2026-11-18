# CDC NOFO Funding MCP — Fidelity Report (PS21-2102 & CE23-2301)

- **Generated:** `2026-11-18T21:13:58Z` (Antigravity, Task F4)
- **Staging build compared:** `places_staging` `funding_report` build `5` (`method_version=nofo-v1`, finished `2026-11-18T21:04:06.428751+00:00`)
- **Read interface:** `app.funding_report.lookup.nofo_dataset()`
- **Reference artifacts:**
  - `/home/john/places-app/data/cdcfundingprofiles/PS21-2102_Recipient_Dossier.xlsx` (Generated July 17, 2026; USAspending federal action obligation with FY2026 partial through March 2026; pre-November 2026 TAGGS snapshot)
  - `/home/john/places-app/data/reports/ce23_2301_subawardees/` (`CDC-RFA-CE23-2301_subawardee_report.md`, `ce23_2301_distinct_subawardees.csv`, `ce23_2301_subaward_actions.csv`; USAspending sub-awards ingested July 3, 2026)

## Executive Summary

1. **PS21-2102 recipient set and FY2021–FY2025 obligations match 100% to the dollar.** Both lookup and reference contain the exact same **97** recipients (0 missing, 0 extra). Across all **97 recipients × 5 fiscal years (485 cells)**, both File C (`account_obligation`) and prime-transaction (`award_obligation`) totals equal the reference workbook with **0 discrepancies** (`$229,148,853` total).
2. **PS21-2102 FY2026 difference (`+$10,166,689`, 93 recipients) is 100% explained by data date and basis.** The reference workbook used award-level obligations through March 2026 (`$0` across all 97 recipients). Lookup's primary basis is File C (`usaspending_account`, complete through **FY2026 P12**), adding `$10,166,689` across 93 recipients (`$0` File C rows for 3 recipients; `null` for `NU62PS924733` Brothers Health Collective which has no FY2026 File C row). Lookup's comparison `award_obligation` for FY2026 remains `$0` (34 recipients with `$0.00` REVISION rows, 63 `null`) because USAspending FY2026 prime refresh was blocked upstream (WP FR).
3. **PS21-2102 other-awards and OpDiv differences (77 recipients) are 100% explained by two factors:**
   - **Scope clarification between workbook tabs:** In the reference workbook, `Recipient Summary` (`Other Awards Total ($)`) sums **all** non-PS21 HHS awards (**696 awards / $2,025,515,221**; equivalent to Lookup's `sum(recipient.other_awards.total)` = **734 awards / $2,247,925,474**), whereas the `Other Federal Awards` tab and `Portfolio Analysis` OpDiv rollup sum only the **top-10 per recipient** (**485 rows / $1,906,774,736**; equivalent to Lookup's `aggregates.other_awards_top10_total` = **495 rows / $2,106,319,827**). Comparing apples-to-apples, top-10 rows increased by **+10** (`+$199,545,091`) and all-other-awards increased by **+38** (`+$222,410,253`).
   - **November 2026 TAGGS refresh (`IFY2026`):** Staging `taggs.raw_awards` was refreshed on `2026-11-18T18:34Z` (`taggs.ingestion_runs.id=2`, `merged_2026-11-v2`, 65 files, 876,649 rows), adding full-year `issue_date_fiscal_year = 2026` actions across all HHS OpDivs. Across all 196 differing common top-10 awards, **136** equal the FY2026 TAGGS amount to the exact dollar, **59** already had partial FY2026 in July 2026 and gained the remainder/revisions in November 2026, and the sole remaining award (`H7600208`, LivWell) already reflected an early-IFY2026 `-$2` FY2024 adjustment in July plus `+$566,289` FY2026 in November. All **28** lookup-only top-10 awards were either first issued in `IFY2026` (**17**) or grew in `IFY2026` into the top 10 (**11**); all **18** reference-only top-10 awards remain positive in TAGGS and were displaced below rank 10. **Zero unexplained discrepancies remain.**
4. **CE23-2301 sub-awards match 100% through July 3, 2026, plus 2 newly reported July 27, 2026 actions (`+$218,331.93`).** Both have **5** distinct sub-awardees, **3** prime awards with sub-awards, and **1** duplicate removed. Lookup's refreshed `usaspending_subawards` (through `2026-09-30`, WP FR) adds exactly 2 FY2026 actions dated `2026-07-27` under prime `NUS4CE002311` (`$142,531.00` to Sitkans Against Family Violence and `$75,800.93` to Haa Tooch Licheesh), accounting for 100% of the `$1,962,872.68 -> $2,181,204.61` delta.

---

## Staging Build Source Data-Through Dates

| Source ID | Publisher | Product | Coverage | Data Through |
|---|---|---|---|---|
| `usaspending_account` | USAspending.gov | Federal account award data (File C), CDC | FY2020–FY2026 | `FY2026 P12` |
| `usaspending_award` | USAspending.gov | CDC assistance prime transactions | CDC assistance awards | `2026-06-18` |
| `taggs` | HHS TAGGS | HHS award actions | FY2021–FY2026 funding fiscal years | `null` (unknown) |
| `usaspending_subawards` | USAspending.gov | Assistance sub-award reports | CDC prime-linked sub-awards | `2026-09-30` |

> **Metadata caveat:** `taggs.raw_awards.action_issue_date` is `NULL` on all 876,649 staged rows, so `sources[taggs].data_through` is `null` (`unknown`). However, `taggs.ingestion_runs` (`id=2`, `2026-11-18T18:34:46Z`) confirms staging holds the `merged_2026-11-v2` TAGGS refresh including full `issue_date_fiscal_year = 2026` files.

---

## Part 1: CDC-RFA-PS21-2102 vs `PS21-2102_Recipient_Dossier.xlsx`

### 1.1 Portfolio-Level Comparison

| Metric | Reference Workbook (Jul 17, 2026) | Staging Lookup (Build 5, Nov 18, 2026) | Delta (Lookup − Ref) | Cause |
|---|---:|---:|---:|---|
| Recipient count | 97 | 97 | 0 | Exact 1:1 FAIN match |
| FY2021 obligations | $42,395,995 | $42,395,995 | $0 | Exact match (account & award) |
| FY2022 obligations | $49,347,654 | $49,347,654 | $0 | Exact match (account & award) |
| FY2023 obligations | $52,613,214 | $52,613,214 | $0 | Exact match (account & award) |
| FY2024 obligations | $42,395,995 | $42,395,995 | $0 | Exact match (account & award) |
| FY2025 obligations | $42,395,995 | $42,395,995 | $0 | Exact match (account & award) |
| **FY2021–FY2025 subtotal** | **$229,148,853** | **$229,148,853** | **$0** | **0 diffs across 485 recipient-year cells** |
| FY2026 obligations (primary) | $0 | $10,166,689 | +$10,166,689 | File C FY2026 P12 vs Mar-2026 award-level (93 recipients) |
| FY2026 obligations (award-level comparison) | $0 | $0 | $0 | FY2026 prime file stays at 2026-06-18 (WP FR upstream block) |
| **PS21-2102 best-available total** | **$229,148,853** | **$239,315,542** | **+$10,166,689** | **100% from FY2026 File C P12 obligations** |
| Other HHS awards — total count (all non-PS21) | 696 | 734 | +38 | Nov-2026 TAGGS `IFY2026` refresh |
| Other HHS awards — total amount (all non-PS21) | $2,025,515,221 | $2,247,925,474 | +$222,410,253 | Matches `Recipient Summary` scope; Nov-2026 TAGGS refresh |
| Other HHS awards — top-10 row count | 485 | 495 | +10 | Nov-2026 TAGGS refresh (28 added, 18 displaced) |
| **Other HHS awards — top-10 total** | **$1,906,774,736** | **$2,106,319,827** | **+$199,545,091** | **Matches `Other Federal Awards` & OpDiv tab scope** |
| Recipients without other HHS awards | 10 | 9 | -1 | 1 recipient(s) gained first TAGGS other awards in `IFY2026` (NU62PS924741) |

### 1.2 Other HHS Awards by Operating Division (Top-10 Lists Rollup)

| OpDiv | Ref Awards | Lookup Awards | Delta Awards | Ref Total ($) | Lookup Total ($) | Delta ($) |
|---|---:|---:|---:|---:|---:|---:|
| HRSA | 266 | 272 | +6 | $1,382,809,067 | $1,522,326,712 | +$139,517,645 |
| SAMHSA | 152 | 154 | +2 | $226,175,482 | $260,598,907 | +$34,423,425 |
| ACF | 21 | 22 | +1 | $240,672,704 | $253,237,440 | +$12,564,736 |
| CDC | 44 | 45 | +1 | $55,709,076 | $68,748,361 | +$13,039,285 |
| DHHS/OS | 2 | 2 | +0 | $1,408,407 | $1,408,407 | $0 |
| **Total** | **485** | **495** | **+10** | **$1,906,774,736** | **$2,106,319,827** | **+$199,545,091** |

### 1.3 Every PS21-2102 Recipient Whose Values Differ

- **FY2021–FY2025 per-recipient differences:** `0` of 97 recipients (**none**).
- **FY2026 File C P12 differences:** `93` of 97 recipients (`4` recipients have `$0` or `null` in FY2026 File C: `NU62PS924694` ARCARE `$0`, `NU62PS924737` Centro de Salud de la Comunidad de San Ysidro `$0`, `NU62PS924733` Brothers Health Collective `null`, `NU62PS924711` Detroit Recovery Project `$0`).
- **Other-award count or dollar differences:** `77` of 97 recipients (all explained by the November 2026 TAGGS `IFY2026` refresh).
- **Recipients differing on at least one numeric field (FY2026 and/or other awards):** `97` of 97 (`0` identical on every field).
- **Display name variants:** `38` recipients have a different display string in lookup vs the workbook solely because `nofo-v1` selects the longest name variant across USAspending and TAGGS (e.g., `INC.` vs `INC`, `INCORPORATED`, or historical legal name); every FAIN and UEI matches 1:1.

| # | State | FAIN | Recipient (Lookup Longest Variant) | FY21–25 Diff | FY26 File C (Ref $0) | Other Cnt (Ref→Cur) | Other Top-10 $ (Ref → Cur) | Top-10 Delta | Reason |
|---:|---|---|---|---:|---:|---:|---|---:|---|
| 1 | AL | `NU62PS924730` | BIRMINGHAM AIDS OUTREACH INC | $0 | +$110,417 | 2 | $2,600,000 → $3,250,000 | +$650,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 2 | AL | `NU62PS924739` | HEALTH SERVICES CENTER, INC. | $0 | +$110,417 | 10 | $15,210,983 → $18,493,635 | +$3,282,652 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 3 | AR | `NU62PS924694` | ARCARE | $0 | $0 | 17→19 | $97,316,247 → $105,889,645 | +$8,573,398 | TAGGS Nov-2026 IFY2026 refresh (count 17->19; 1 top-10 swap(s)) |
| 4 | AZ | `NU62PS924675` | SOUTHERN ARIZONA AIDS FOUNDATION | $0 | +$108,359 | 2 | $1,964,789 → $1,757,583 | -$207,206 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 5 | AZ | `NU62PS924676` | SOUTHWEST CENTER FOR HIV/AIDS, INC. | $0 | +$110,417 | 3 | $2,967,362 → $4,300,695 | +$1,333,333 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 6 | CA | `NU62PS924690` | ALTAMED HEALTH SERVICES CORPORATION | $0 | +$110,406 | 42→43 | $154,019,970 → $168,540,631 | +$14,520,661 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 42->43; 2 top-10 swap(s)) |
| 7 | CA | `NU62PS924693` | APLA HEALTH & WELLNESS | $0 | +$110,417 | 10 | $20,555,005 → $22,428,497 | +$1,873,492 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 8 | CA | `NU62PS924726` | BAY AREA COMMUNITY HEALTH | $0 | +$110,417 | 14→17 | $67,362,577 → $72,005,307 | +$4,642,730 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 14->17) |
| 9 | CA | `NU62PS924729` | BIENESTAR HUMAN SERVICES, INC. | $0 | +$110,417 | 7 | $12,774,996 → $13,874,995 | +$1,099,999 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 10 | CA | `NU62PS924737` | CENTRO DE SALUD DE LA COMUNIDAD DE SAN YSIDRO, INC. | $0 | $0 | 27→28 | $114,429,266 → $124,238,815 | +$9,809,549 | TAGGS Nov-2026 IFY2026 refresh (count 27->28; 1 top-10 swap(s)) |
| 11 | CA | `NU62PS924716` | FAMILY HEALTH CENTERS OF SAN DIEGO, INC. | $0 | +$110,417 | 28→29 | $159,154,010 → $174,528,335 | +$15,374,325 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 28->29; 1 top-10 swap(s)) |
| 12 | CA | `NU62PS924747` | JWCH INSTITUTE, INC. | $0 | +$110,417 | 20 | $67,620,637 → $74,155,052 | +$6,534,415 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (1 top-10 swap(s)) |
| 13 | CA | `NU62PS924751` | LOS ANGELES LGBT CENTER | $0 | +$110,406 | 18 | $29,173,587 → $31,216,107 | +$2,042,520 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 14 | CA | `NU62PS924674` | SAN FRANCISCO AIDS FOUNDATION | $0 | +$110,417 | 2 | $1,500,000 → $2,000,000 | +$500,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 15 | CA | `NU62PS924678` | SUTTER BAY HOSPITALS | $0 | +$110,417 | 2 | $937,460 → $1,537,350 | +$599,890 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 16 | CA | `NU62PS924680` | Via Care Community Health Center, Inc. | $0 | +$110,417 | 15→16 | $26,151,976 → $30,575,599 | +$4,423,623 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 15->16; 1 top-10 swap(s)) |
| 17 | CO | `NU62PS924704` | COLORADO HEALTH NETWORK, INC. | $0 | +$110,417 | 2 | $917,025 → $911,952 | -$5,073 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 18 | CT | `NU62PS924692` | APEX COMMUNITY CARE, INC. | $0 | +$110,417 | 5 | $4,895,787 → $5,441,811 | +$546,024 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 19 | CT | `NU62PS924686` | APNH: A PLACE TO NOURISH YOUR HEALTH, INC. | $0 | +$110,417 | 0 | $0 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 20 | DC | `NU62PS924748` | LA CLINICA DEL PUEBLO, INC. | $0 | +$110,417 | 12 | $23,202,471 → $27,854,663 | +$4,652,192 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 21 | DC | `NU62PS924682` | WHITMAN-WALKER CLINIC, INC. | $0 | +$110,417 | 13 | $24,842,914 → $26,915,579 | +$2,072,665 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 22 | FL | `NU62PS924687` | AIDS SERVICE ASSOCIATION OF PINELLAS, INC. | $0 | +$110,417 | 0 | $0 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 23 | FL | `NU62PS924725` | BASIC NWFL, INC. | $0 | +$110,417 | 1 | $247,761 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 24 | FL | `NU62PS924731` | BORINQUEN HEALTH CARE CENTER, INC. | $0 | +$110,406 | 16→17 | $69,748,621 → $76,382,129 | +$6,633,508 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 16->17) |
| 25 | FL | `NU62PS924735` | CARE RESOURCE COMMUNITY HEALTH CENTERS INCORPORATED | $0 | +$110,417 | 9 | $33,934,866 → $35,920,333 | +$1,985,467 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 26 | FL | `NU62PS924717` | FOUNDCARE INC. | $0 | +$110,417 | 8 | $23,619,270 → $26,235,560 | +$2,616,290 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 27 | FL | `NU62PS924724` | Health Care Center For The Homeless, Inc. | $0 | +$26,815 | 9 | $35,480,736 → $38,194,984 | +$2,714,248 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 28 | FL | `NU62PS924741` | HOPE AND HELP CENTER OF CENTRAL FLORIDA, INC. | $0 | +$110,406 | 0→1 | $0 → $314,244 | +$314,244 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 0->1; +1 new top-10 award(s)) |
| 29 | FL | `NU62PS924749` | LATINOS SALUD, INC | $0 | +$110,417 | 1 | $354,597 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 30 | FL | `NU62PS924698` | METROPOLITAN CHARITIES, INC. | $0 | +$110,406 | 7→8 | $5,991,560 → $7,596,241 | +$1,604,681 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 7->8; +1 new top-10 award(s)) |
| 31 | FL | `NU62PS924681` | THE VILLAGE SOUTH, INC. | $0 | +$110,417 | 5→6 | $9,468,359 → $11,089,760 | +$1,621,401 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 5->6; +1 new top-10 award(s)) |
| 32 | FL | `NU62PS924679` | TREASURE COAST HEALTH COUNCIL, INC. | $0 | +$110,417 | 1 | $9,368,031 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 33 | GA | `NU62PS924684` | AID ATLANTA, INCORPORATED | $0 | +$110,417 | 2 | $2,900,873 → $3,535,842 | +$634,969 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 34 | GA | `NU62PS924696` | ATLANTA HARM REDUCTION COALITION, INC. | $0 | +$110,417 | 7 | $7,147,924 → $8,047,214 | +$899,290 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 35 | GA | `NU62PS924652` | NAESM, INC. | $0 | +$110,417 | 2 | $1,800,000 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 36 | GA | `NU62PS924715` | POSITIVE IMPACT HEALTH CENTERS INC. | $0 | +$110,417 | 16→17 | $17,623,371 → $21,586,316 | +$3,962,945 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 16->17) |
| 37 | GA | `NU62PS924673` | RECOVERY CONSULTANTS OF ATLANTA, INCORPORATED | $0 | +$110,417 | 11 | $16,712,474 → $19,935,900 | +$3,223,426 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 38 | GA | `NU62PS924651` | "SOMEONE CARES" INC. OF ATLANTA | $0 | +$110,417 | 3 | $2,768,631 → $3,168,631 | +$400,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 39 | IL | `NU62PS924789` | ALLIANCE CARE 360 | $0 | +$110,417 | 1→2 | $1,064,000 → $1,714,000 | +$650,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 1->2; +1 new top-10 award(s)) |
| 40 | IL | `NU62PS924733` | BROTHERS HEALTH COLLECTIVE | $0 | null | 1 | $800,000 → $530,640 | -$269,360 | TAGGS Nov-2026 IFY2026 refresh |
| 41 | IL | `NU62PS924657` | PUERTO RICAN CULTURAL CENTER | $0 | +$110,417 | 5 | $5,214,843 → $6,214,843 | +$1,000,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 42 | IL | `NU62PS924658` | SOUTH SIDE HELP CENTER, INC. | $0 | +$110,417 | 0 | $0 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 43 | IN | `NU62PS924734` | BROTHERS UNITED, INCORPORATED | $0 | +$110,417 | 1 | $897,674 → $1,121,795 | +$224,121 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 44 | IN | `NU62PS924710` | DAMIEN CENTER INC, THE | $0 | +$110,417 | 5→7 | $6,606,992 → $8,768,299 | +$2,161,307 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 5->7; +2 new top-10 award(s)) |
| 45 | KY | `NU62PS924740` | LIVWELL COMMUNITY HEALTH SERVICES, INC. | $0 | +$110,417 | 1 | $2,882,728 → $3,449,017 | +$566,289 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (H7600208 IFY2026 (+$566,289 FY26; -$2 FY24 already in ref)) |
| 46 | LA | `NU62PS924723` | HIV/AIDS ALLIANCE FOR REGION TWO (HAART), INC. | $0 | +$110,417 | 9 | $15,773,566 → $19,077,038 | +$3,303,472 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 47 | LA | `NU62PS924709` | NO AIDS TASK FORCE | $0 | +$110,417 | 20 | $36,350,740 → $40,849,141 | +$4,498,401 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (1 top-10 swap(s)) |
| 48 | LA | `NU62PS924707` | PRIORITY HEALTH CARE | $0 | +$110,417 | 5 | $6,517,526 → $7,547,348 | +$1,029,822 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 49 | MA | `NU62PS924700` | MULTICULTURAL AIDS COALITION INC | $0 | +$110,417 | 1 | $800,000 → $705,513 | -$94,487 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 50 | MD | `NU62PS924656` | HEART TO HAND INC | $0 | +$110,417 | 1 | $150,000 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 51 | MI | `NU62PS924705` | COMMUNITY HEALTH AWARENESS GROUP | $0 | +$110,417 | 3 | $2,900,480 → $3,300,480 | +$400,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 52 | MI | `NU62PS924711` | DETROIT RECOVERY PROJECT | $0 | $0 | 16→17 | $18,599,042 → $20,304,801 | +$1,705,759 | TAGGS Nov-2026 IFY2026 refresh (count 16->17; 1 top-10 swap(s)) |
| 53 | MI | `NU62PS924752` | MATRIX HUMAN SERVICES | $0 | +$110,417 | 5 | $207,979,528 → $215,381,545 | +$7,402,017 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 54 | MN | `NU62PS924654` | ALIVENESS PROJECT, INC., THE | $0 | +$110,416 | 1 | $1,000,000 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 55 | MN | `NU62PS924745` | INDIGENOUS PEOPLES TASK FORCE | $0 | +$110,406 | 3 | $2,649,046 → $2,611,972 | -$37,074 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 56 | MO | `NU62PS924706` | COMMUNITY WELLNESS PROJECT, THE | $0 | +$110,417 | 1 | $1,662,500 → $2,062,500 | +$400,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 57 | MS | `NU62PS924746` | INSTITUTE FOR THE ADVANCEMENT OF MINORITY HEALTH | $0 | +$110,417 | 1 | $3,000,000 → $4,000,000 | +$1,000,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 58 | MS | `NU62PS924653` | MY BROTHER'S KEEPER, INC. | $0 | +$110,417 | 5 | $9,099,685 → $9,999,685 | +$900,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 59 | NC | `NU62PS924655` | QUALITY HOME CARE SERVICES | $0 | +$110,417 | 10 | $7,555,300 → $8,561,409 | +$1,006,109 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 60 | NJ | `NU62PS924743` | HYACINTH AIDS FOUNDATION INC | $0 | +$110,417 | 3 | $2,707,529 → $3,014,543 | +$307,014 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 61 | NJ | `NU62PS924754` | NEWARK BETH ISRAEL MEDICAL CENTER, INC. | $0 | +$110,417 | 2 | $3,579,084 → $4,220,308 | +$641,224 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 62 | NJ | `NU62PS924713` | North Jersey Aids Alliance, Inc | $0 | +$110,417 | 11→13 | $10,457,479 → $14,271,087 | +$3,813,608 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 11->13; 1 top-10 swap(s)) |
| 63 | NV | `NU62PS924720` | GAY AND LESBIAN COMMUNITY CENTER OF SOUTHERN NEVADA, INC. | $0 | +$110,417 | 2 | $1,533,122 → $2,233,100 | +$699,978 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 64 | NV | `NU62PS924744` | IMPACT EXCHANGE | $0 | +$110,417 | 0 | $0 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 65 | NY | `NU62PS924650` | African Services Committee, Inc. | $0 | +$110,417 | 1 | $682,931 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 66 | NY | `NU62PS924688` | AIDS SERVICE CENTER OF LOWER MANHATTAN, INC. | $0 | +$110,417 | 5→6 | $6,520,000 → $7,770,000 | +$1,250,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 5->6; +1 new top-10 award(s)) |
| 67 | NY | `NU62PS924732` | BRONXCARE HEALTH SYSTEM | $0 | +$110,417 | 13→14 | $10,819,547 → $11,188,955 | +$369,408 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 13->14; 1 top-10 swap(s)) |
| 68 | NY | `NU62PS924753` | MONTEFIORE MEDICAL CENTER | $0 | +$110,417 | 26→30 | $59,329,286 → $64,604,978 | +$5,275,692 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 26->30; 1 top-10 swap(s)) |
| 69 | NY | `NU62PS924702` | NEW YORK AND PRESBYTERIAN HOSPITAL, THE | $0 | +$110,417 | 11→12 | $7,100,899 → $8,612,880 | +$1,511,981 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 11->12; 1 top-10 swap(s)) |
| 70 | NY | `NU62PS924703` | NEW YORK CITY HEALTH AND HOSPITALS CORPORATION | $0 | +$110,417 | 9→10 | $7,567,786 → $8,031,004 | +$463,218 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 9->10; +1 new top-10 award(s)) |
| 71 | NY | `NU62PS924660` | SUNSET PARK HEALTH COUNCIL, INC. | $0 | +$110,417 | 33→37 | $148,624,863 → $164,795,497 | +$16,170,634 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 33->37; 1 top-10 swap(s)) |
| 72 | OH | `NU62PS924712` | EQUITAS HEALTH, INC. | $0 | +$110,417 | 8 | $6,262,432 → $7,086,231 | +$823,799 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 73 | OK | `NU62PS924721` | GUIDING RIGHT, INC. | $0 | +$110,417 | 3 | $3,022,133 → $3,522,133 | +$500,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 74 | OR | `NU62PS924736` | CASCADE AIDS PROJECT | $0 | +$110,417 | 4 | $1,812,292 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 75 | OR | `NU62PS924722` | HIV ALLIANCE | $0 | +$110,417 | 0 | $0 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 76 | PA | `NU62PS924728` | BEBASHI - TRANSITION TO HOPE | $0 | +$110,417 | 0 | $0 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 77 | PA | `NU62PS924708` | CONGRESO DE LATINOS UNIDOS, INC. | $0 | +$110,417 | 1 | $900,000 → $1,500,000 | +$600,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 78 | PR | `NU62PS924695` | Aspira Inc. Of Puerto Rico | $0 | +$98,927 | 0 | $0 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 79 | PR | `NU62PS924699` | Migrant Health Center Western Region, Inc. | $0 | +$110,417 | 22→24 | $73,676,895 → $83,264,391 | +$9,587,496 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 22->24; 1 top-10 swap(s)) |
| 80 | SC | `NU62PS924714` | PALMETTO AIDS LIFE SUPPORT SERVICES | $0 | +$110,406 | 1 | $678,548 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 81 | TN | `NU62PS924697` | METHODIST LE BONHEUR COMMUNITY OUTREACH | $0 | +$110,417 | 10→11 | $11,109,670 → $13,857,567 | +$2,747,897 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 10->11; 1 top-10 swap(s)) |
| 82 | TN | `NU62PS924701` | NASHVILLE CARES (COUNCIL ON AIDS RESOURCES, EDUCATION, AND SERVICES) | $0 | +$110,417 | 0 | $0 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 83 | TX | `NU62PS924683` | ABOUNDING PROSPERITY INCORPORATED | $0 | +$110,406 | 16 | $10,403,433 → $11,443,858 | +$1,040,425 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (1 top-10 swap(s)) |
| 84 | TX | `NU62PS924672` | AIDS ARMS, INC. | $0 | +$110,417 | 8→9 | $8,250,469 → $9,870,997 | +$1,620,528 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 8->9; +1 new top-10 award(s)) |
| 85 | TX | `NU62PS924685` | AIDS FOUNDATION HOUSTON, INC.. | $0 | +$110,417 | 1 | $362,006 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 86 | TX | `NU62PS924689` | AIDS SERVICES OF AUSTIN, INC | $0 | +$110,417 | 2 | $506,001 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 87 | TX | `NU62PS924727` | BEAT AIDS COALITION TRUST | $0 | +$110,417 | 2 | $1,354,597 → $1,604,597 | +$250,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 88 | TX | `NU62PS924649` | CIVIC HEART COMMUNITY SERVICES | $0 | +$110,417 | 5 | $6,218,115 → $7,392,165 | +$1,174,050 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 89 | TX | `NU62PS924738` | COASTAL BEND WELLNESS FOUNDATION, INC. | $0 | +$110,417 | 17→18 | $20,257,401 → $23,216,266 | +$2,958,865 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 17->18; 1 top-10 swap(s)) |
| 90 | TX | `NU62PS924719` | FUNDACION LATINOAMERICANA DE ACCION SOCIAL, INC. | $0 | +$110,417 | 3 | $3,325,000 → $3,825,000 | +$500,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 91 | TX | `NU62PS924742` | HOUSTON AREA COMMUNITY SERVICES, INC. | $0 | +$110,417 | 6 | $56,642,240 → $60,976,501 | +$4,334,261 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 92 | TX | `NU62PS924677` | SPECIAL HEALTH RESOURCES FOR TEXAS, INCORPORATED | $0 | +$110,417 | 17 | $25,066,332 → $29,081,238 | +$4,014,906 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 93 | TX | `NU62PS924659` | VALLEY AIDS COUNCIL | $0 | +$110,417 | 3 | $7,130,391 → $8,269,372 | +$1,138,981 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 94 | VA | `NU62PS924691` | INOVA HEALTH CARE SERVICES | $0 | +$110,406 | 3 | $7,309,883 → $8,903,533 | +$1,593,650 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |
| 95 | VA | `NU62PS924750` | LGBT LIFE CENTER | $0 | +$110,417 | 2→3 | $3,400,000 → $3,950,000 | +$550,000 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh (count 2->3; +1 new top-10 award(s)) |
| 96 | VI | `NU62PS924718` | FREDERIKSTED HEALTH CARE INC | $0 | +$110,417 | 0 | $0 (same) | $0 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0) |
| 97 | WI | `NU62PS924648` | Aids Resource Center Of Wisconsin, Inc. | $0 | +$105,575 | 2 | $3,896,586 → $4,728,028 | +$831,442 | FY2026 File C P12 obligation (ref used Mar-2026 award-level $0); TAGGS Nov-2026 IFY2026 refresh |

---

## Part 2: CDC-RFA-CE23-2301 Sub-Awards vs `data/reports/ce23_2301_subawardees/`

### 2.1 Summary Comparison

| Metric | Reference Report (Ingested Jul 3, 2026) | Staging Lookup (Build 5, Data Through 2026-09-30) | Delta (Lookup − Ref) | Cause |
|---|---:|---:|---:|---|
| Distinct sub-awardees (by UEI) | 5 | 5 | 0 | Exact match |
| Prime awards with sub-awards | 3 | 3 | 0 | Exact match |
| Deduplicated sub-award actions | 12 | 14 | +2 | 2 new `2026-07-27` FY2026 actions |
| Raw USAspending sub-award records | 13 | 15 | +2 | 2 new `2026-07-27` raw records |
| Duplicate raw records removed | 1 | 1 | 0 | Exact match (same deduplication rule) |
| **Deduplicated reported sub-award amount** | **$1,962,872.68** | **$2,181,204.61** | **+$218,331.93** | **100% from 2 new `2026-07-27` actions** |

### 2.2 Sub-Awards by Fiscal Year

| Fiscal Year | Ref Actions | Lookup Actions | Ref Sub-awardees | Lookup Sub-awardees | Ref Amount | Lookup Amount | Delta |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 2023 | 3 | 3 | 3 | 3 | $405,000.00 | $405,000.00 | $0.00 |
| 2024 | 2 | 2 | 2 | 2 | $524,743.33 | $524,743.33 | $0.00 |
| 2025 | 3 | 3 | 3 | 3 | $515,785.20 | $515,785.20 | $0.00 |
| 2026 | 4 | 6 | 3 | 4 | $517,344.15 | $735,676.08 | +$218,331.93 |

### 2.3 Per-Sub-Awardee Comparison (All 5 Distinct Organizations)

| Sub-Awardee UEI | Name | State | Prime FAIN | Ref Actions → Lookup | Ref Amount | Lookup Amount | Delta | Reason |
|---|---|---|---|---:|---:|---:|---:|---|
| `EA3XVE1ZJG41` | GRANT-BLACKFORD MENTAL HEALTH, INC | IN | `NUS4CE002322` | 4 → 4 | $1,142,138.53 | $1,142,138.53 | $0.00 | Exact match |
| `DMALML7F3J93` | SITKANS AGAINST FAMILY VIOLENCE | AK | `NUS4CE002311` | 3 → 4 | $413,390.00 | $555,921.00 | +$142,531.00 | Later data date (WP FR refresh through 2026-09-30): +1 FY2026 action dated 2026-07-27 |
| `DYMCE9W6G6Q3` | DOMESTIC VIOLENCE SHELTER & SERVICES INC | NC | `NUS4CE002315` | 2 → 2 | $242,344.15 | $242,344.15 | $0.00 | Exact match |
| `H7BCE22Q2EJ3` | HAA TOOCH LICHEESH | AK | `NUS4CE002311` | 2 → 3 | $110,000.00 | $185,800.93 | +$75,800.93 | Later data date (WP FR refresh through 2026-09-30): +1 FY2026 action dated 2026-07-27 |
| `QGS3LJYZJE57` | AIDING WOMEN FROM ABUSE & RAPE EMERGENCIES INC | AK | `NUS4CE002311` | 1 → 1 | $55,000.00 | $55,000.00 | $0.00 | Exact match |

### 2.4 New Sub-Award Actions Explaining 100% of the CE23-2301 Delta

| Prime FAIN | Sub-award Number | Action Date | FY | Sub-awardee UEI | Sub-awardee Name | Amount | SAM Report ID |
|---|---|---|---:|---|---|---:|---|
| `NUS4CE002311` | `DELTA AHEAD SAFV 4` | 2026-07-27 | 2026 | `DMALML7F3J93` | SITKANS AGAINST FAMILY VIOLENCE | $142,531.00 | `F920716C-B343-4147-94FD-99AD9C5FE344` |
| `NUS4CE002311` | `DELTA AHEAD SA 4` | 2026-07-27 | 2026 | `H7BCE22Q2EJ3` | HAA TOOCH LICHEESH | $75,800.93 | `830FFDAF-4ABC-466A-A618-D2081E97E8D9` |

Sum of the 2 new `2026-07-27` actions: **$218,331.93** (`$1,962,872.68 + $218,331.93 = $2,181,204.61`). No reference actions were dropped or altered.

