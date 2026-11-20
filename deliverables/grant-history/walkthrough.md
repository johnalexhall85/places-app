# CDC Grant History & State Funding MCP — Staging Walkthrough Checklist

Generated from read-only SQL and `app.state_funding.lookup` against `places_staging`, **CHIP state funding build 7** (`state-funding-v1`, through **FY2026 P12**) and **funding report build 7** (`nofo-v1`, through **FY2026 P12** / prime & sub-award actions through `2026-09-30`).

**Formatting notes (Contract §4):**
- Whole dollars are shown in KPI tiles, bars, and tables (rounded with JS `Math.round`); CSV exports keep exact cents.
- Negative values carry minus `−` (U+2212); positive values carry no `+`.
- Source line on active FY2026 NOFOs reads: `Source: USAspending · Award financial (File C), CDC · FY2026 P12 · CHIP state funding build 7; HHS TAGGS; Grants.gov`.

---

## 1. PS21-2102 (`/cdc-funding/grant/CDC-RFA-PS21-2102`)

Also confirm canonical URL replacement by visiting `/cdc-funding/grant/PS21-2102` and verifying the address bar updates to `/cdc-funding/grant/CDC-RFA-PS21-2102`.

- [ ] **Header & metadata:**
  - Title: *Comprehensive High-Impact HIV Prevention Programs for Community-Based Organizations* (`NOFO title (Grants.gov)`)
  - Latest FY: **FY2026** (`FY2026 P12`, no pre-2026 "last fiscal year with obligations" banner)
- [ ] **KPI tiles:**
  - **FY2026 obligations:** **$10,166,689** (exact SQL: `$10,166,689.00`) · Regular **$10,166,689** · Supplemental **$0**
  - **FY2021–FY2026 total:** **$239,315,542** (exact SQL: `$239,315,542.00`)
  - **Recipients in FY2026:** **96** (96 current awards; 97 total awards/recipients across all years)
  - **States and territories in FY2026:** **34**
- [ ] **Top 3 states (in "By state, FY2026" and default "Recipients" grouping):**
  1. **Texas (`TX`):** **$1,214,576** (`$1,214,576.00`) · `11 current` (`11 current · 0 past`)
  2. **Florida (`FL`):** **$1,130,952** (`$1,130,952.00`) · `11 current` (`11 current · 0 past`)
  3. **California (`CA`):** **$1,104,148** (`$1,104,148.00`) · `11 current` (`11 current · 0 past`)
- [ ] **Search by recipient name:** Enter `civic heart`
  - Returns **1** row under Texas (`1 of 11 shown`): **CIVIC HEART COMMUNITY SERVICES** (`NU62PS924649`, `$110,417`).
- [ ] **Search by UEI:** Clear search and enter `DC4UE8MU2ZE8`
  - Returns **1** row under New York (`1 of 7 shown`): **SUNSET PARK HEALTH COUNCIL, INC.** (`NU62PS924660`, `$110,417`).
- [ ] **Past-recipient count:** **1** past award / recipient across the NOFO.
  - Under **Illinois** (`3 current · 1 past`, FY2026 total `$331,251`), confirm **BROTHERS HEALTH COLLECTIVE** (`NU62PS924733`, UEI `VLHMZ1B9DAJ4`) appears after the 3 current Illinois rows with `—` in the FY2026 column and muted `Last funded FY2022` (all-years total `$58,632`).

---

## 2. Largest FY2026 NOFO: TU-24-0137 (`/cdc-funding/grant/CDC-RFA-TU-24-0137`)

- [ ] **Header & metadata:**
  - Title: *Public Health Emergency Preparedness (PHEP) Cooperative Agreement* (`NOFO title (Grants.gov)`)
  - Latest FY: **FY2026** (`FY2026 P12`)
- [ ] **KPI tiles:**
  - **FY2026 obligations:** **$655,656,715** (exact SQL: `$655,656,715.00`) · Regular **$655,656,715** · Supplemental **$0**
  - **FY2021–FY2026 total:** **$1,958,854,536** (exact SQL: `$1,958,854,536.00`)
  - **Recipients in FY2026:** **62** (62 current awards across FY2024–FY2026)
  - **States and territories in FY2026:** **57** (56 states & territories plus `State not recorded` `'__'` with 3 awards totaling `$1,268,643`)
- [ ] **Top 3 states:**
  1. **California (`CA`):** **$65,898,427** (`$65,898,427.00`) · `2 current · 0 past`
  2. **Texas (`TX`):** **$42,915,264** (`$42,915,264.00`) · `1 current · 0 past`
  3. **New York (`NY`):** **$40,370,783** (`$40,370,783.00`) · `2 current · 0 past`
- [ ] **Search by recipient name:** Enter `county of los angeles`
  - Returns **1** row under California (`1 of 2 shown`): **COUNTY OF LOS ANGELES** (`NU90TU000042`, `$21,449,471`).
- [ ] **Search by UEI:** Clear search and enter `NFHJD7V9MGN3`
  - Returns **1** row under Texas (`1 of 1 shown`): **DEPARTMENT OF STATE HEALTH SERVICES** (`NU90TU000053`, `$42,915,264`).
- [ ] **Past-recipient count:** **0** past recipients (every group shows `0 past`; toggling "Show past recipients" leaves all 62 rows visible).

---

## 3. Pre-FY2026 Latest-Funded NOFO: OT20-2004 (`/cdc-funding/grant/CDC-RFA-OT20-2004`)

- [ ] **Pre-FY2026 label check:**
  - Title: *Supporting Tribal Public Health Capacity in Coronavirus Preparedness and Response* (`NOFO title (Grants.gov)`)
  - Hero displays: **`FY2021 is the last fiscal year with obligations.`**
  - KPI tiles reflect **FY2021** as the latest year:
    - **FY2021 obligations:** **$10,746,901** (Regular `$0` · Supplemental `$10,746,901`)
    - **FY2021–FY2026 total:** **−$4,378,298** (exact SQL: `−$4,378,297.98`, reflecting FY2022–FY2024 supplemental de-obligations)
    - **Recipients in FY2021:** **315** · **States and territories in FY2021:** **32**
    - **Past recipients (not funded in FY2021):** **31** (346 total awards)
  - Top 3 states: **Alaska** (`$2,547,104`, 65 current · 4 past), **California** (`$2,099,945`, 56 current · 7 past), **Washington** (`$850,000`, 25 current · 3 past).
  - Source line reads `... · FY2021 P12 · CHIP state funding build 7; HHS TAGGS; Grants.gov`.
  - *(Optional second pre-FY2026 check: `/cdc-funding/grant/CDC-RFA-CK19-1904` displays **`FY2023 is the last fiscal year with obligations.`** with FY2023 total `$1,085,918,040` across 59 states/territories and 64 recipients.)*

---

## 4. Generic Staging Checks

- [ ] **Phone width (375 px):** Resize viewport to `375 × 812` on `/cdc-funding/grant/CDC-RFA-PS21-2102`. Verify no horizontal page scroll (`document.documentElement.scrollWidth <= 375`), KPI tiles stack cleanly, tables scroll within `.sf-scroll`, and controls remain usable.
- [ ] **Sorting:** On `CDC-RFA-PS21-2102`, test `Sort by`:
  - `State total` (`Descending` → Texas first; `Ascending` → lowest state total first);
  - `State name` (`Ascending` → Alabama first);
  - `Recipient` (`Ascending` → alphabetical within each state group);
  - `Recipient type` and `FY2026 amount` (`Ascending` / `Descending`).
  - Confirm URL query parameters (`sort`, `dir`) update and survive reload.
- [ ] **Past toggle:** On `CDC-RFA-PS21-2102`, uncheck **Show past recipients**. Confirm `past=0` appears in the URL and **BROTHERS HEALTH COLLECTIVE** disappears from Illinois (leaving 3 rows). Re-check to confirm it returns. (On `CDC-RFA-OT20-2004`, unchecking hides 31 past rows, leaving 315.)
- [ ] **Lazy expand (history + sub-awards):**
  - On `CDC-RFA-PS21-2102`, click **CIVIC HEART COMMUNITY SERVICES** (`NU62PS924649`, Texas). Confirm a lazy fetch to `/api/state-funding/v1/grants/CDC-RFA-PS21-2102/awards/ASST_NON_NU62PS924649_075` renders:
    - UEI `DY23EUM3YRW5`, Houston TX, district `TX-18`, recipient type `Non-Profit Public Non-Government Organizations (taggs_recipient_class)`;
    - 6-year history (`FY2021` `$441,625`, `FY2022` `$761,531`, `FY2023` `$781,625`, `FY2024` `$441,625`, `FY2025` `$441,625`, `FY2026` `$110,417`) and award total **$2,978,448**;
    - Budget category `HIV/AIDS, Viral Hepatitis, STI and TB Prevention: $110,417`;
    - Sub-awards container `[data-subawards-for="ASST_NON_NU62PS924649_075"]` showing **`2 sub-awardees · 2 actions · $639,812 reported`** plus the not-additional-funding sentence.
  - On `CDC-RFA-TU-24-0137`, expand **COUNTY OF LOS ANGELES** (`NU90TU000042`, California): 3-year history (`FY2024` `$21,452,890`, `FY2025` `$21,451,983`, `FY2026` `$21,449,471`, total **$64,354,344**) and **`5 sub-awardees · 16 actions · $5,832,194 reported`** (exact `$5,832,193.50`).
- [ ] **CSV download:** Click **Download CSV** on `/cdc-funding/grant/CDC-RFA-PS21-2102`. Verify:
  - Filename is `chip-cdc-grant-CDC-RFA-PS21-2102.csv`.
  - Line 1 starts with `# Source: USAspending · Award financial (File C), CDC · FY2026 P12 · CHIP state funding build 7; HHS TAGGS; Grants.gov`.
  - Columns match Contract §3 (`state`, `split_state`, `is_current`, ..., `FY2026_regular`, `FY2026_supplemental`, `FY2026_total`, `FY2021_total`..`FY2026_total`, `all_years_total`, `subawardee_count`, `subaward_reported_amount`, `usaspending_url`).
  - Data row count is **97** (96 current + 1 past), and amounts preserve exact cents.
- [ ] **State-page grant link and back:**
  - Open `/cdc-funding/state/CA`, search `CDC-RFA-PS21-2102` (11 awards, total `$1,104,148`), click a grant name link (or `Grant history` in an expanded row) → lands on `/cdc-funding/grant/CDC-RFA-PS21-2102`.
  - In "By state, FY2026", click California's **State profile** link → returns to `/cdc-funding/state/CA?fy=2026&award_type=grant&q=CDC-RFA-PS21-2102` showing **11 awards** totaling **$1,104,148** (`$1,104,148.00`).
- [ ] **Unknown NOFO suggestions:** Visit `/cdc-funding/grant/CDC-RFA-PS21-9999`. Verify an error state with a `Retry` button and clickable suggestion links: `CDC-RFA-PS21-2102`, `CDC-RFA-PS21-2103`, `CDC-RFA-PS21-2104`, `CDC-RFA-PS21-2105`, `CDC-RFA-PS21-2107`. Clicking `CDC-RFA-PS21-2102` loads the PS21-2102 page.
- [ ] **Anonymous API 401:** Without a staging session cookie, request `GET /api/state-funding/v1/grants/CDC-RFA-PS21-2102` (and `/api/state-funding/v1/grants/CDC-RFA-PS21-2102.csv`). Verify both return HTTP **401**.

---

## 5. Beta MCP Connector Prompts (claude.ai)

Try these prompts with the staging CHIP MCP connector enabled and confirm the tool calls, numbers, and source citations match SQL:

1. **State summary (`get_state_funding`):**
   - *Prompt:* `"What were California's FY2026 CDC grants in CHIP, broken down into regular and supplemental obligations and top budget category?"`
   - *Expected answer:* FY2026 P12 grants total **$275,957,458.00** (Regular **$393,477,480.14**, Supplemental **−$117,520,022.14**), **294** grants across **110** recipients. Largest budget category: **HIV/AIDS, Viral Hepatitis, STI and TB Prevention (`HIV`)** at **$117,367,081.47** (regular `$117,367,081.47`, supplemental `$0`). Cites USAspending File C FY2026 P12 and notes that negative supplemental reflects reductions to earlier emergency obligations.
2. **State grant search & top grant (`list_state_grants`):**
   - *Prompt:* `"List California's FY2026 CDC grants under NOFO CDC-RFA-PS21-2102, and also tell me California's single largest FY2026 CDC grant by absolute obligation amount."`
   - *Expected answer:* Under `CDC-RFA-PS21-2102`, **11** California grants totaling **$1,104,148.00** (for example `NU62PS924674`, San Francisco AIDS Foundation, `$110,417.00`). Largest California FY2026 grant by absolute amount: **Immunization and Vaccines for Children** (`NH23IP922612`, `CDC-RFA-IP19-1901`, `PUBLIC HEALTH, CALIFORNIA DEPARTMENT OF`) at **−$87,227,926.50** (all supplemental de-obligation).
3. **Grant history by state (`get_grant_history`):**
   - *Prompt:* `"Show the funding history and top states for CDC grant PS21-2102, including whether any past recipients were not funded in its latest year."`
   - *Expected answer:* Latest funded year **FY2026** (`FY2026 P12`) total **$10,166,689.00** across **96** recipients in **34** states; FY2021–FY2026 total **$239,315,542.00** across **97** awards. Top 3 states: **Texas** (`$1,214,576`, 11 current), **Florida** (`$1,130,952`, 11 current), **California** (`$1,104,148`, 11 current). **1** past recipient (`BROTHERS HEALTH COLLECTIVE` in Illinois, last funded FY2022).
4. **Past-recipient count (`get_grant_history`):**
   - *Prompt:* `"How many current vs. past recipients does CDC grant NH28CE4 have, and which state leads its latest year?"`
   - *Expected answer:* Latest funded year **FY2026** (`$4,113,496.84`), **52** current awards across **25** states and **139** past awards (**191** total across FY2021–FY2026, all-years total `$33,373,948.32`). Top state in FY2026: **New York** (`$681,106.64`, 9 current, 11 past).
