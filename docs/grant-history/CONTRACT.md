# Grant history contract, v1 (2026-11-20)

Owner: Claude. Codex implements §1–§5, and Antigravity audits against §7. Any change needs a dated amendment here, written by Claude.

Method version: `grant-history-v1`. There is no new table or build. Everything is read at request time from the active `state_funding` build (money, names, categories) and the active `funding_report` build (recipient identity, type, abstract, period, sub-awards). The state funding contract ([../state-funding/CONTRACT.md](../state-funding/CONTRACT.md), with Amendments 1–2) still governs the state page, except where §5 below adds to it.

## 1. Definitions

- **Grant:** a CDC NOFO, identified by `fon_key`. Any form the user types (`CDC-RFA-PS21-2102`, `PS21-2102`, `ps212102`) resolves through `app.funding_report.keys.nofo_key`.
- **Awards in scope:** `state_funding.award` rows in the active build with `award_type = 'grant'` and `fon_key` equal to the key.
- **Money:** `state_funding.obligation.amount` for those awards, FY2021–FY2026. This includes state `'__'`, which is shown as "State not recorded". `regular` and `supplemental` follow `is_supplemental`. The page applies no other filter.
- **Latest fiscal year (`latest_fy`):** the largest `fiscal_year` for which the in-scope awards' total `amount` is greater than 0. If no year qualifies, use the largest year with any row and set `latest_fy_note` to "No fiscal year from FY2021 to FY2026 has a positive net obligation for this grant."
- **Current award:** an award with any obligation row in `latest_fy`, even when its net is 0 or negative. Every other in-scope award is a **past award**.
- **Award state (for grouping):**
  - A current award appears under **each** state where it has `latest_fy` rows, with that state's `latest_fy` amount. An award with rows in two states appears twice, with `split_state = true`.
  - A past award appears once, under the state with the largest absolute amount in its most recent fiscal year with rows. Ties are broken alphabetically.
  - This makes each state's `latest_fy` total equal the sum of its rows. It also equals the state page's grants for that state and year restricted to this NOFO.
- **Recipient type** (`recipient_type`, with `recipient_type_source`):
  1. the TAGGS `recipient_class` from the `funding_report` profile, with source `taggs_recipient_class`;
  2. otherwise the USAspending `business_types` joined with `"; "` as the source writes them, with source `usaspending_business_types`;
  3. otherwise `"Not stated"`, with source `none`.

  Awards that have no `funding_report` profile take identity fields from `state_funding.award` and recipient type "Not stated".
- **Grant name:** `nofo_title` for the key, Grants.gov first and then CDC Funding Profiles, as in the state contract §1.2 rules 1–2. Without a title, use `funding_report.nofo.fon_display`, with `name_source = 'fon'`.

## 2. Lookup

### `app.state_funding.lookup.grant_history(db, nofo)`

This is a pure read. It raises a not-found error, with up to five suggestions taken from `funding_report.lookup.resolve_nofo`, when:
- the key is unknown;
- the NOFO is not a CDC NOFO;
- the NOFO has no in-scope awards with obligation rows.

It returns:

```jsonc
{ "nofo": { "nofo_key": "PS212102", "fon_display": "CDC-RFA-PS21-2102", "fon_variants": ["…"],
            "grant_name": "…", "name_source": "grants_gov_nofo_title",
            "cfda": [{ "number": "93.939", "title": "…", "award_count": 97 }],
            "awarding_offices": ["…"],
            "period_of_performance": { "start_min": "2021-07-01", "end_max": "2026-06-30" },
            "categories": [{ "code": "…", "name": "…", "basis": "…", "total": 0.0 }] },   // latest_fy, abs(total) desc
  "latest_fy": 2026, "latest_fy_period": "FY2026 P12", "latest_fy_note": null,
  "fiscal_years": [2026, 2025, 2024, 2023, 2022, 2021],
  "totals": { "latest_fy": { "total": 0.0, "regular": 0.0, "supplemental": 0.0,
                             "award_count": 0, "recipient_count": 0, "state_count": 0 },
              "all_years": { "total": 0.0, "award_count": 0, "recipient_count": 0 } },
  "by_fiscal_year": [ { "fiscal_year": 2021, "regular": 0.0, "supplemental": 0.0, "total": 0.0,
                        "award_count": 0, "is_complete": true } ],            // ascending, all six years, zeros kept
  "by_state": [ { "state": "CA", "name": "California", "latest_fy_total": 0.0, "regular": 0.0,
                  "supplemental": 0.0, "current_count": 0, "past_count": 0 } ],
                  // latest_fy_total desc, then name; states with only past awards last (total null); "__" last of all
  "awards": [ {
      "award_unique_key": "ASST_NON_…", "award_id": "NU62PS924730", "state": "AL", "split_state": false,
      "is_current": true,
      "recipient_name": "…", "recipient_uei": "…", "city": "…",
      "recipient_type": "State Government", "recipient_type_source": "taggs_recipient_class",
      "is_state_government": true, "project_title": "…",
      "latest_fy_amount": { "regular": 0.0, "supplemental": 0.0, "total": 0.0 },   // null for past awards
      "history": [ { "fiscal_year": 2021, "regular": 0.0, "supplemental": 0.0, "total": 0.0 } ],
          // ascending; only years with rows; summed over all states for the award
      "all_years_total": 0.0, "first_fy": 2021, "last_fy": 2026,
      "subawards": { "subawardee_count": 0, "action_count": 0, "reported_amount": 0.0 },  // null when no profile
      "usaspending_url": "https://…" } ],
      // order: state as in by_state, then current before past, then latest_fy_amount.total desc, then recipient_name
  "citation": "Source: USAspending · Award financial (File C), CDC · FY2026 P12 · CHIP state funding build 1; HHS TAGGS; Grants.gov",
  "notes": [ "…" ],
  "build": { "state_funding_build_id": 1, "funding_report_build_id": 1, "method_version": "grant-history-v1" } }
```

Rules:
- `recipient_count` counts distinct `coalesce(recipient_uei, recipient_name)`.
- Amounts are rounded to cents.
- `split_state` award rows each carry the state's own `latest_fy_amount`, while `history` and `all_years_total` stay award-wide. The page must not add `all_years_total` across those rows.
- `notes` always contains these sentences:
  - "Amounts are net CDC obligations from USAspending (File C) for FY2021–FY2026. Earlier years are not included."
  - "A recipient's state is the state USAspending records for the recipient, not where services are delivered."
  - "Sub-award amounts are reported by prime recipients and are not additional federal funding."
- `notes` adds the state contract's negative-supplemental sentence when any latest-FY supplemental is below 0.
- `notes` adds a sentence naming any fiscal year that is not complete.

### `app.state_funding.lookup.grant_award(db, nofo, award_unique_key)`

This returns the expanded-row detail for one award under the NOFO, and raises not-found otherwise. It includes:
- `recipient_name`, `name_variants`, `recipient_uei`, and `parent`;
- `address` (`line1`, `city`, `state`, `zip`, and `county`);
- `congressional_district`, with its source;
- the TAGGS `recipient_type` (organization type), labelled `organization_type`;
- `business_types` and `metro_status`;
- `project_title`, the full `abstract`, and `abstract_source`;
- `cfda` and `funding_office`;
- `period_of_performance`;
- `categories` for `latest_fy` (the same shape as state contract Amendment 1 rows, with `accounts[]`);
- `history`, as in `grant_history`;
- `subawards`, as in `grant_history`;
- `usaspending_url`.

The profile fields come from `funding_report` and the money comes from `state_funding`.

### `app.funding_report.lookup`

Add read-only helpers only, and do not change the builder:
- `award_profiles(session, key)`, which returns `{award_unique_key: profile}`;
- `award_subaward_summaries(session, key)`, which returns `{award_unique_key: {subawardee_count, action_count, reported_amount}}`. It uses the same deduplication as `_subaward_block` and matches on the prime FAIN or the award key.

## 3. HTTP API (prefix `/state-funding/v1`, behind the demo gate)

- `GET /grants/{nofo}` returns `grant_history`. The response is 404 with `{"detail": …, "suggestions": [...]}` when the grant is not found.
- `GET /grants/{nofo}/awards/{award_unique_key}` returns `grant_award`.
- `GET /grants/{nofo}.csv` writes one row per entry in `awards`, in that order. Its columns are:
  - `state`, `split_state`, `is_current`;
  - `recipient_name`, `recipient_uei`, `city`, `recipient_type`, `recipient_type_source`;
  - `project_title`, `award_id`;
  - `FY{latest}_regular`, `FY{latest}_supplemental`, `FY{latest}_total`;
  - `FY2021_total` … `FY2026_total`;
  - `all_years_total`;
  - `subawardee_count`, `subaward_reported_amount`;
  - `usaspending_url`.

  The first line is `# ` followed by the citation. The filename is `chip-cdc-grant-{fon_display}.csv`.

## 4. Page (`/cdc-funding/grant/{nofo}`)

- **Brand and conventions:** the same brand, tokens, header, source lines, and formatting as `/cdc-funding/state/{code}`. Every amount shows its sign. The layout works at 375 px with no horizontal page scroll. Meaning is never carried by colour alone.
- **Canonical URL:** if the path is not the `fon_display`, replace it with the `fon_display` (history `replaceState`).

Sections, top to bottom:

1. **Summary.**
   - Title: the grant name with its source label. Beneath it, the FON and any variants, the assistance listing(s), the awarding office(s), the period of performance, and the budget categories.
   - KPI tiles:
     - "FY{latest} obligations", with regular and supplemental in small type;
     - "FY2021–FY{last} total";
     - "Recipients in FY{latest}";
     - "States and territories in FY{latest}".
   - The latest-FY label says "last fiscal year with obligations" when `latest_fy` < the newest year in `fiscal_years`, and shows `latest_fy_note` if set.
   - A small bar chart of `by_fiscal_year.total`, with negative values below a zero line and `latest_fy` marked, plus a "Show as table" toggle and the source line. It follows the profile chart style (small and plain). It is not a dashboard band.
2. **By state, FY{latest}.** A compact ranked list or bar of `by_state`: state, total, and current recipients. Clicking a state scrolls to its group in the list. Each state name also links to `/cdc-funding/state/{code}?fy={latest}&award_type=grant&q={fon_display}`.
3. **Recipients.**
   - Controls:
     - a search box, which matches recipient name, project title, award ID, UEI, city, and recipient type, requires every term, and is case-insensitive;
     - a toggle, "Show past recipients" (on by default);
     - sort by state total (default), state name, recipient, recipient type, or FY{latest} amount, ascending or descending.
   - The list is grouped by state. Each group header shows the state name, its FY{latest} total, and "N current · M past". When a search is active, it shows "k of n shown". Within a group, current awards come first, sorted by the chosen column; past awards follow.
   - Columns: Recipient (with a "Split across states" marker if `split_state`), Recipient type, Project title, FY{latest} obligations. Past rows show "—" in the amount column and a muted "Last funded FY{last_fy}" note.
   - Expanding a row (button, keyboard accessible) lazily fetches `grant_award` and shows:
     - recipient details (UEI, address, district, organization type, business types, and the recipient type source);
     - the award ID with a USAspending link;
     - the project title and abstract (collapsible after about 600 characters);
     - the assistance listing and the period of performance;
     - "Funding history under this grant": a small per-fiscal-year bar row plus a table of regular, supplemental, and total by FY, and the all-years total;
     - the latest-FY budget categories;
     - "Sub-awards": the sub-awardee count, the action count, and the reported amount, with the not-additional-funding sentence. The container is `<div data-subawards-for="{award_unique_key}">` so a list can be attached later (§6).
   - Below the list: "Download CSV" and the source line.
4. **About these numbers:** the `notes`, plus one sentence: "Other federal awards held by these recipients are not shown here; the CHIP recipient profile report lists them."

The query string keeps `q`, `past` (0 or 1), `sort`, `dir`, and `open` (one expanded award key) so views can be shared.

Loading, empty, and error states (with a retry) are required. An unknown NOFO shows the suggestions as links.

## 5. Additions to the state page (`/cdc-funding/state/{code}`)

- In the grants table, a grant's name links to `/cdc-funding/grant/{fon}` when the award has a `fon`. The expanded row adds a "Grant history" link. Awards without a `fon` are not linked.
- The state API's `/grants` rows already carry `fon`. No state-API change is needed.
- The `q` filter already matches `fon`, so the link back from §4.2 works as is. Check that `q=CDC-RFA-PS21-2102` returns exactly that NOFO's awards. If it does not, report it in the status file; do not change the matching rule.

## 6. Planned later: sub-awardee list (not built in v1)

This is reserved, so v1 must not use these names for anything else:
- `GET /grants/{nofo}/awards/{award_unique_key}/subawards`, which will return `funding_report` sub-awardee rows for that prime award (name, UEI, location, action count, reported amount, and fiscal years);
- the page's `data-subawards-for` container.

## 7. Audit (Antigravity, `backend/tests/test_grant_history_audit.py`)

These run against the active builds on `places_staging`. The NOFOs are the 10 largest by FY2026 grant total, plus PS212102, OT202004, NH28CE4, and the NOFO with the most split-state awards.

1. For every fiscal year, the sum of `by_fiscal_year.total` across the selected NOFOs equals the SQL sum of `obligation.amount` for grant awards with those `fon_key`s, within $0.01.
2. `totals.latest_fy.total` = the sum of `by_state.latest_fy_total` = the sum of the current awards' `latest_fy_amount.total`.
3. For each state in `by_state` (excluding `'__'`), `latest_fy_total` equals the sum of `total` over `app.state_funding.lookup.grants` rows for that state, `fy=latest_fy`, `award_type=grant`, whose `fon_key` is the NOFO. Page through every row.
4. Each award's `history` equals its SQL per-FY sums, and `all_years_total` equals the sum of `history`.
5. `latest_fy` follows the §1 rule, checked independently in SQL.
6. Every award in scope appears at least once. Only current awards appear more than once, and only with `split_state = true`.
7. MCP: `get_grant_history` and `get_state_funding` return the same totals as the lookup for two NOFOs and two states.
