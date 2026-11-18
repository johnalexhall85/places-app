# CDC NOFO recipient profiles through the CHIP MCP server

Status: approved by John 2026-11-18. Claude manages; Codex and Antigravity build under the ownership rules in the root `AGENTS.md`.

## Goal

A user asks an AI assistant: "Recipient profile for CDC NOFO CDC-RFA-PS21-2102, with sub-awardees." The assistant calls the public CHIP MCP server, downloads the NOFO dataset into its code sandbox, and renders a Word report and an Excel workbook in the Public Data Observatory CHIP brand. The reference for structure and content is John's PS21-2102 Recipient Dossier (`data/cdcfundingprofiles/PS21-2102_Recipient_Dossier.{docx,xlsx}`). The reference is not the reference for styling; the PDO Brand & Style Guide v1.0 is.

Deliverables: (1) three MCP funding tools and a dataset route, live at `mcp.publicdataobservatory.org`; (2) a claude.ai skill zip, `chip-nofo-recipient-profile.zip`.

Scope: CDC NOFOs only. Other HHS funding opportunities are recognized and refused with an explanation.

## Data method (version `nofo-v1`)

The read model lives in schema `funding_report` (migration `b3f9d2a7c1e4`). `python -m app.funding_report.build` rebuilds it from source tables it never modifies:

| Need | Source |
|---|---|
| NOFO to award link | `cdc_funding.raw_usaspending_assistance_prime_transactions.raw_record->>'funding_opportunity_number'` (CDC, award level), plus `taggs.raw_awards.fon` for `opdiv = 'CDC'`, joined on FAIN = `award_number` |
| Obligations by fiscal year (primary) | `cdc_funding.cdc_funding_awards.transaction_obligated_amount` (account level, File C, the table behind `/cdc-funding`), joined on `award_unique_key` = `assistance_award_unique_key` |
| Award-level obligations (comparison) | `federal_action_obligation` by `action_date_fiscal_year`, from the prime transactions above |
| TAGGS amounts (comparison) | `taggs.raw_awards.sum_of_actions` by `funding_fiscal_year` |
| Identity, address, district, abstract, period, business types | USAspending prime transactions first, then the account-level award row, then TAGGS |
| Organization class, type, metro | TAGGS `recipient_class`, `recipient_type`, `metro_non_metro` |
| Other HHS awards | TAGGS rows with the same UEI and a different NOFO, grouped by `award_number`, `SUM(sum_of_actions) > 0`, ranked by amount |
| Sub-awards | `cdc_funding.raw_usaspending_assistance_subawards`, joined on `prime_award_fain` or `prime_award_unique_key` |

Rules carried over from the proven scripts (`backend/scripts/build_ce24_0027_recipient_dossier.py`, `build_nofo_subawardee_reports.py`):

- **NOFO key:** uppercase, keep letters and digits, strip a leading `CDCRFA`. `CDC-RFA-PS21-2102`, `PS21-2102`, and `ps 21 2102` all become `PS212102`. Display form: the most common full FON string.
- **Best-available total per award:** the account-level sum when the award has account rows; otherwise the award-level sum; otherwise TAGGS. The basis is recorded (`account`, `award`, `taggs`).
- **Congressional district:** USAspending current, then original, then TAGGS. The source is recorded. No geocoding.
- **Recipient name:** the longest name variant; all variants are kept.
- **Sub-award deduplication:** prime FAIN, subaward number, action date, sub-awardee UEI, amount, and description identify one action; the SAM report ids of duplicates are kept. Sub-award amounts are reported by prime recipients and are never added to prime obligations.
- **Fiscal-year completeness:** a fiscal year is complete when `cdc_funding_import_runs` records it as complete (FY2026 is complete at P12 as of 2026-11-18). Award-level and TAGGS data carry their own data-through dates; they are reported, not assumed.

Verified 2026-11-18 for PS21-2102: the account-level join gives FY2021–FY2025 of $42,395,995 / $49,347,654 / $52,613,214 / $42,395,995 / $42,395,995 (equal to the reference) and FY2026 $10,166,689.

## Dataset contract `chip.nofo_recipient_profile.v1`

Returned by `GET /funding/nofo/{nofo_key}.json?subawards=0|1` and by `app.funding_report.lookup.nofo_dataset()`. Money is a JSON number in dollars with cents. Missing values are `null`, never `0`. Lists are sorted as stated.

```jsonc
{
  "schema_version": "chip.nofo_recipient_profile.v1",
  "build": {"build_id": 3, "built_at": "...", "method_version": "nofo-v1"},
  "sources": [            // one per source used; each has a ready citation string
    {"id": "usaspending_account", "publisher": "USAspending.gov", "product": "Federal account award data (File C), CDC",
     "coverage": "FY2021–FY2026", "data_through": "FY2026 P12", "citation": "Source: USAspending.gov · ..."},
    {"id": "usaspending_award", ...}, {"id": "taggs", ...}, {"id": "usaspending_subawards", ...}
  ],
  "nofo": {
    "nofo_key": "PS212102", "fon_display": "CDC-RFA-PS21-2102", "fon_variants": ["..."],
    "awarding_agency": "Centers for Disease Control and Prevention", "awarding_offices": ["..."],
    "cfda": [{"number": "93.939", "title": "...", "award_count": 97}],
    "period_of_performance": {"start_min": "2021-07-01", "end_max": "2026-06-30"},
    "award_count": 97, "recipient_count": 97,
    "fiscal_years": [{"fiscal_year": 2021, "account_obligation": 0.0, "award_obligation": 0.0,
                      "taggs_amount": 0.0, "is_complete": true}],
    "best_available_total": 0.0
  },
  "aggregates": {
    "by_state":            [{"state": "CA", "recipients": 11, "nofo_total": 0.0, "other_awards_top10_total": 0.0}], // recipients desc, state asc
    "by_recipient_class":  [{"value": "...", "recipients": 60, "nofo_total": 0.0}],      // "(unspecified)" for null
    "by_recipient_type":   [{"value": "...", "recipients": 26}],
    "by_metro":            [{"value": "Metro", "recipients": 92}],
    "other_awards_by_opdiv": [{"opdiv": "HRSA", "awards": 266, "total": 0.0}],           // top-10 lists only
    "other_awards_by_aln":   [{"aln": "93224", "title": "...", "awards": 25, "total": 0.0}], // top 15 by total
    "top_recipients_by_other_awards": [{"award_unique_key": "...", "recipient_name": "...", "state": "MI",
                                        "other_award_count": 5, "other_awards_top10_total": 0.0}], // top 15
    "other_awards_top10_total": 0.0, "other_award_rows": 485, "recipients_without_other_awards": 10
  },
  "recipients": [ /* profile objects, sorted by state then recipient_name */ {
    "award_unique_key": "ASST_NON_NU62PS924730_075", "fain": "NU62PS924730", "uei": "W42VM3PLXYE4",
    "recipient_name": "...", "name_variants": ["..."], "parent": {"uei": null, "name": null},
    "address": {"line1": "...", "line2": null, "city": "...", "state": "AL", "zip": "35233", "county": "JEFFERSON", "country": "UNITED STATES"},
    "congressional_district": "AL-07", "congressional_district_source": "usaspending_current",
    "recipient_class": "...", "recipient_type": "...", "metro_status": "Metro", "business_types": ["..."],
    "project_title": "...", "abstract": "... (full text; renderers truncate)",
    "cfda": {"number": "93.939", "title": "..."}, "funding_office": "...",
    "period_of_performance": {"start": "2021-07-01", "end": "2026-06-30"},
    "totals": {"account_obligation": 0.0, "award_obligation": 0.0, "taggs_amount": 0.0,
               "best_available": 0.0, "best_available_basis": "account"},
    "fiscal_years": [{"fiscal_year": 2021, "account_obligation": 0.0, "award_obligation": 0.0, "taggs_amount": 0.0}],
    "usaspending_url": "https://www.usaspending.gov/award/ASST_NON_NU62PS924730_075/",
    "other_awards": {"count": 2, "total": 0.0, "top10_total": 0.0, "top": [
      {"rank": 1, "award_number": "...", "amount": 0.0, "opdiv": "CDC", "aln": "93939", "aln_title": "...",
       "fon": "...", "first_fiscal_year": 2022, "last_fiscal_year": 2025, "award_title": "..."}]},
    "subawards": null    // when subawards=1: {"subawardee_count": 0, "action_count": 0, "reported_amount": 0.0}
  }],
  "subawards": null,     // when subawards=1:
  /* {"summary": {"distinct_subawardees": 5, "actions": 12, "raw_records": 13, "duplicates_removed": 1,
                  "reported_amount": 0.0, "primes_with_subawards": 3},
       "by_fiscal_year": [{"fiscal_year": 2023, "actions": 3, "subawardees": 3, "reported_amount": 0.0}],
       "by_state": [{"state": "AK", "subawardees": 3}],
       "subawardees": [{"uei": "...", "name": "...", "name_variants": [], "dba_names": [], "business_types": [],
                        "address": {...}, "congressional_district": "IN-05", "prime_fains": [], "prime_recipients": [],
                        "action_count": 4, "reported_amount": 0.0, "first_action_date": "...", "last_action_date": "...",
                        "fiscal_years": [{"fiscal_year": 2023, "actions": 1, "reported_amount": 0.0}],
                        "description_examples": ["..."]}],          // reported_amount desc
       "actions": [{"prime_fain": "...", "prime_recipient": "...", "subaward_number": "...", "action_date": "...",
                    "fiscal_year": 2023, "amount": 0.0, "subawardee_uei": "...", "subawardee_name": "...",
                    "description": "...", "sam_report_ids": [], "usaspending_url": "..."}]} */
  "caveats": ["...plain sentences the report prints verbatim..."]
}
```

Caveats always include: sub-award amounts are not additional federal funding; "other federal awards" are HHS awards in TAGGS only (top 10 per recipient shown), not a complete federal portfolio; the data-through date of each source; and any fiscal year that is not complete.

## MCP surface (Amendment 3 to the tool contract)

- `get_nofo_overview(nofo, include_subawards=false)`: the `nofo` block, `aggregates`, the sub-award `summary` when asked, `sources`, `caveats`, and `dataset_url`. On no match: `ToolError` with up to 5 suggestions. On a non-CDC funding opportunity: `ToolError` naming its HHS operating division and saying only CDC is supported.
- `list_nofo_recipients(nofo, offset=0, limit=50)` (limit 1–100): compact recipient rows (name, state, district, UEI, FAIN, best-available total, other-award count).
- `get_recipient_funding(nofo, recipient)`: one full profile; `recipient` matches a UEI, FAIN, or award key exactly, or a name substring when that is unique within the NOFO.
- `GET /funding/nofo/{nofo_key}.json?subawards=0|1`: the full dataset; gzip; `Cache-Control: public, max-age=3600`; `ETag` from the build id. Not an MCP tool; the overview returns its absolute URL, built from `CHIP_MCP_PUBLIC_BASE_URL`.

Funding responses use the same `Envelope`. Their `sources` come from the dataset `sources` and their `interpretation_rules` from the funding rules below. Funding tools never call `app.area_pilot.lookup` and area tools never read `funding_report`.

Funding interpretation rules (verbatim):
1. Obligations are USAspending federal account (File C) obligations unless a row says otherwise; award-level and TAGGS amounts are shown for comparison and can differ.
2. Sub-award amounts are reported by prime recipients and are not additional federal funding; never add them to prime obligations.
3. Other federal awards are HHS awards recorded in TAGGS for the same UEI; they are not a complete federal funding portfolio.
4. State the data-through date of each source and say when a fiscal year is not complete.
5. Do not rank recipients by merit or describe funding as good or bad; report amounts, periods, and sources.

## Skill

`skills/chip-nofo-recipient-profile/` (zip root is that folder): `SKILL.md` (Claude), `scripts/render.py` and helpers (Codex), `assets/` (PDO report template, CHIP logo, `brand.json`), `references/report_spec.md`. The renderer takes the dataset JSON and an optional narrative JSON, writes `<FON>_Recipient_Profile.docx` and `.xlsx`, and composes every number itself. The assistant never retypes data.

## Work packages

| WP | Owner | Content | Status |
|---|---|---|---|
| FR | Claude | Refresh FY2026 award-level files (`backend/scripts/fetch_usaspending_cdc_award_files.py`) and ingest on staging | staging done for sub-awards; prime blocked upstream (see below) |
| F0 | Claude | This plan, contract amendment, migration, role grants, task files | done |
| F1+F2 | Codex | `backend/app/funding_report/` build and lookup; MCP tools and dataset route | |
| F3 | Codex | Renderer, assets, zip script | |
| F4 | Antigravity | Funding eval questions and the PS21-2102 / CE23-2301 fidelity report | |
| F5 | Claude | Review, merge to `beta`, staging deploy; Gate A: John tries the skill in claude.ai | |
| F6 | Claude | Gate B: live migration, build, nginx, restart, final zip | |

## FR outcome (2026-11-18)

- **Download:** on 2026-11-18, USAspending returned **no FY2026 HHS assistance prime transactions**. The CDC FY2026 grant transaction count was 0. HHS overall had 404. All agencies together had 374,987, and the Department of Education had 22,659. FY2025 CDC data is still present. The bulk download produced a header-only prime file. The July file in `data/usaspending/chipfunding/fy26/` (22,208 rows through 2026-06-18) remains the award-level source.
- **Sub-awards were available:** 7,120 CDC FY2026 assistance sub-award rows, through 2026-09-30.
  - Folder: `data/usaspending/chipfunding/fy26_candidate/`.
  - Profile: `fy26_subaward_refresh_profile.json`. It keeps the July prime and contract files and swaps in only the new sub-award file.
- **Staging:** `ingest_usaspending_funding.py --profile-path …/fy26_subaward_refresh_profile.json --fiscal-year 2026 --replace` against `places_staging` took 2 minutes. Results:
  - FY2026 assistance sub-awards went from 3,373 to 7,120.
  - Prime (22,208), contracts (1,886 / 109), and `fact_cdc_funding_prime_transaction` (24,094) are unchanged.
- **Live:** not changed. Repeat the same command against `places` at Gate B.
- **Consequence:** awards first made after 2026-06-18 still have no NOFO link. Account-level obligations through FY2026 P12 are unaffected. Retry the prime download later with `fetch_usaspending_cdc_award_files.py`.

## FY2026 full-year award data (2026-11-18, after Gate A)

- **Source.** USAspending's search and bulk-download index serves no FY2026 HHS assistance transactions. Its per-award pages still have them, and so does the monthly **Award Data Archive** `FY2026_075_Assistance_Full_20261106.zip` (262,541 HHS rows, of which 41,364 are CDC-awarded, through 2026-09-30; SHA-256 in `data/usaspending/chipfunding/fy26_archive_20261106/SHA256SUMS`). In that archive, `funding_opportunity_number` is blank on all but 704 CDC rows. 21,768 of those same transactions had it in CHIP's July download.
- **Restoring the FONs.** `backend/scripts/prepare_usaspending_cdc_archive.py` writes the CDC rows with the FON restored, adding a `chip_fon_backfill` column that records the source:
  - `usaspending`: 704 rows;
  - `previous_transaction` (same transaction key in the July file): 21,768;
  - `award_history` (the award's single FON in earlier raw rows): 18,297;
  - blank: 595, all on awards with more than one historical FON. The builder still links these awards through their earlier rows.
- **Contracts.** The FY2026 files are the union of the awarding-CDC and funding-CDC bulk downloads: 5,012 prime rows and 161 sub-award rows (`fy26_candidate/CDC_Contracts_*_awarding_or_funding_20261118.csv`). The July files had 1,886 and 109. Assistance has no funding-only CDC rows.
- **Ingest.** Profile `data/usaspending/chipfunding/fy26_archive_20261106/fy26_full_year_profile.json`, run with `ingest_usaspending_funding.py --fiscal-year 2026 --replace`.
  - **Staging:** FY2026 raw assistance prime rows went from 22,208 to 41,364, sub-awards from 3,373 to 7,120, and contracts from 1,886 to 5,012. The fact table now has 46,376 rows.
  - **Build 7:** 5,586 NOFOs and 13,687 awards. PS21-2102 FY2026 award-level obligations are $10,166,689, equal to account level.
- **Rollback.** Rerun the ingest with the original profile (`backend/data_profiles/usaspending_funding_file_profile.json --fiscal-year 2026 --replace`; the July files are unchanged in `fy26/`), then rebuild `funding_report`.
