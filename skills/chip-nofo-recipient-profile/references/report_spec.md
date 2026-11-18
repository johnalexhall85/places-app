# NOFO Recipient Profile: report specification

This describes the layout `scripts/render.py` produces from a `chip.nofo_recipient_profile.v1` dataset. The structure follows the PS21-2102 Recipient Dossier. The styling follows the Public Data Observatory Brand & Style Guide v1.0.

## Brand

| Token | Value | Use |
|---|---|---|
| Deep Navy | `#003F61` | cover band, section headings, table header fill |
| Brand Blue | `#0277BD` | sub-headings, links, first chart series |
| Logo Blue | `#3D75C9` | accents |
| Light Background | `#F4F7FB` | alternate table rows, label column |
| Body Text | `#1A2F3F` | body |
| Muted Text | `#546E7A` | source lines, notes |
| Steel Grey | `#CFD8DC` | table borders |
| Data Peach | `#F0B97D` | caveat box border, second chart series |

- **Type:** Roboto Slab Bold for the report title and big stat numbers only. Arial for everything else. Section headings are Arial Bold in Deep Navy; sub-headings are Arial Bold in Brand Blue.
- **Spacing:** multiples of 8 px or 6 pt.
- **Charts:** flat 2D, value-axis gridlines only, labelled axes, never colour alone, and a source line under every chart. Series order: `#0277BD`, `#F0B97D`, `#009688`, `#558B2F`, `#3D75C9`, `#003F61`.
- **Voice:** precise, sourced, and non-partisan. Give the number, the period, and the source. No alarm words and no advocacy.
- **Source line format:** "Source: USAspending.gov · Federal account award data (File C) · FY2021–FY2026 (through FY2026 P12) · CHIP build 3".

## Word report (`<FON>_Recipient_Profile.docx`, US Letter portrait)

The report is built on `assets/PDO_Report_Template.docx`. It keeps that file's styles, header, footer, and closing "About the Public Data Observatory" box. The footer reads "<FON> — Recipient Profile · Page X of Y".

1. **Cover**
   - A Deep Navy cover table with the title "Recipient Profile", the FON, and the program title. The program title is the most common CFDA title, or a title the user supplied.
   - A label/value table with these rows:
     - Funding Opportunity
     - Awarding Agency (and offices)
     - Assistance Listing(s)
     - Period of Performance (the min start to the max end)
     - Recipients Profiled
     - Total obligated (best available), with the fiscal-year range
     - Data Sources, with the data-through date of each source
     - Prepared (the date, "by CHIP, Public Data Observatory")
   - A note line naming any fiscal year that is not complete.
2. **Contents.** A Word TOC field, which updates on open.
3. **Executive Summary.** The Heading 2 sections below. Each fact sentence is generated from `aggregates` and `nofo`. A narrative JSON can add context paragraphs, but it never replaces the numbers.
   - **Summary:** the recipient count, the period, the total obligated, the average per recipient, and what the profile contains.
   - **Key findings box:** the template's KEY FINDINGS table, with 3–4 generated findings, each stating a number.
   - **Obligations by fiscal year:** a one-row table with each fiscal year and the total (an asterisk marks incomplete years), a bar chart PNG of account-level obligations by fiscal year, and a source line.
   - **Where recipients are located:** the number of states and territories, the top states with their counts, and the metro count.
   - **What kinds of organizations they are:** counts by recipient class and by recipient type.
   - **Their wider HHS funding:** the other-awards top-10 total, its ratio to the NOFO total, the count of recipients with no other award, and the OpDiv and assistance-listing leaders.
   - **Data caveat box:** a Light Background fill with a Data Peach left border, listing `caveats` verbatim.
   - **How to read the profiles:** one paragraph.
4. **Profiles.** Heading 1 for each state (its full name), then Heading 2 for each recipient (`recipient_name`), sorted by name within the state. Each profile has:
   - "Also known as:" followed by the other name variants, if there are any.
   - An identity table: UEI · Location (line 1, city, state, ZIP, and "(COUNTY County)") · Congressional District · Organization Class · Organization Type (with "· Metro" or "· Non-Metro") · Business Type.
   - A "<short FON> Award" table: Award Number · Project Title · Assistance Listing · Period of Performance · Total Obligated (best available, with its basis in muted text).
   - "Obligations by fiscal year": a one-row table; an em dash means no obligation was recorded.
   - "Funded project": the abstract, cut at about 900 characters on a word boundary and ending with "…".
   - "Other HHS Awards": a summary line "N other HHS awards recorded · total $X · top 10 shown", then a table with the columns # · Award No. · Amount · OpDiv · Program (award title — assistance-listing title) · FY Range · ALN. If there are none: "No other HHS awards to this recipient are recorded in TAGGS."
   - Sub-awards (only when the dataset has sub-awards and this prime has some): "Sub-awards reported: N sub-awardees · N actions · $X reported (not additional federal funding)."
   - "Source:" followed by the `usaspending_url` as a hyperlink.
5. **Sub-awardees** (only when the dataset has sub-awards): the summary numbers, a table by fiscal year, a table by state, and then one table per prime recipient listing its distinct sub-awardees (name · city/state · district · actions · reported amount · first–last date).
6. **Method and sources.** The `sources` citations, the method from the plan in plain words, and the build id.
7. **About the Public Data Observatory.** The template's closing box.

## Excel workbook (`<FON>_Recipient_Profile.xlsx`)

Every sheet has a header row in Deep Navy with white bold Arial, frozen panes below the header, an auto-filter, currency format `$#,##0` (cents kept in the value), sensible column widths, and alternating Light Background rows.

| Sheet | Content |
|---|---|
| About | Title, FON, agency, assistance listings, period, recipient count, data sources with their data-through dates, the definition of best-available total, the definition of other awards, the caveats, the prepared date, the build id, and a list of tabs |
| Recipient Summary | One row per recipient: # · Recipient · City · State · County · Cong. Dist. · Recipient Class · Org Type · Metro · Award # · Project Title · Total (best available) · Basis · Start · End · # Other Awards · Other Awards Top-10 Total · USAspending Link (hyperlink) |
| Funding by FY | # · Recipient · State · Award # · one column per fiscal year (account obligations) · Total as a `=SUM()` formula, plus a totals row of `SUM` formulas. Incomplete years get an asterisk and a note row. |
| FY Comparison | Recipient · Award # · fiscal year · account · award-level · TAGGS (long format) |
| Other HHS Awards | Recipient · State · Award # · Rank · Other Award # · Amount · OpDiv · ALN · Assistance Listing Title · FON · First FY · Last FY · Award Title |
| Portfolio Analysis | The `aggregates` tables: by state, by recipient class, by recipient type, other awards by OpDiv, top assistance listings, and the top 15 recipients by other-award portfolio |
| Sub-awardees (optional) | One row per distinct sub-awardee |
| Sub-award Actions (optional) | One row per deduplicated action |

## Fixed wording

- "Sub-award amounts are reported by prime recipients and are not additional federal funding."
- "Other HHS awards are awards recorded in TAGGS for the same UEI; they are not a complete account of the organization's federal funding."
- Missing values print as "—", never as $0.
