# CDC State Funding Profile — Staging Walkthrough Checklist (FY2026)

Generated from read-only SQL and `app.state_funding.lookup` against `places_staging`, **CHIP build 7** (`state-funding-v1`, period **FY2026 P12**). Every state grant and all-award total below reconciles to `$0.00` against `cdc_funding.cdc_funding_awards`.

**Formatting notes (Contract Amendment 2):**
- Page default is **Award type = Grants** (`award_type=grant`); title reads `CDC grants to recipients in {State}`. Switching to **All awards** (`award_type=all`) changes the title to `CDC funding to recipients in {State}` and displays the contractor-location note.
- KPI tiles show compact dollars to one decimal place (exact cents appear in the hover `title` tooltip and screen-reader text). Bars and tables show whole dollars (rounded with JS `Math.round`). CSV exports retain exact cents.
- Negative values use minus `−` (U+2212); positive values have no `+`.

---

## Generic Staging Checks

- [ ] **Auth gate (anonymous 401):** Requesting `/api/state-funding/v1/states/CA/summary` without a staging session cookie returns `401`.
- [ ] **Eyebrow & citation:** Eyebrow reads `CDC funding · State profile` (no File C jargon). Source line under both the chart and grants table reads `Source: USAspending · Award financial (File C), CDC · FY2026 P12 · CHIP build 7`.
- [ ] **Phone width (375 px):** Resize viewport to `375 × 812`. Verify no horizontal page scroll (`document.documentElement.scrollWidth <= 375`), KPI labels wrap cleanly without clipping, tables scroll inside their own horizontal container, and NOFO numbers stay on one line (`white-space: nowrap`).
- [ ] **Negative supplemental & sign formatting:** On WY (or CA/TX/PR), verify negative KPI tiles, table amounts, and bar amounts carry `−` (U+2212), positive values carry no `+`, and negative bars extend **left** of the vertical zero line.
- [ ] **Filter chips & URL state:**
  - Change `Award type` to `All awards` and `Funding type` to `Supplemental/emergency`. Verify two filter chips appear (`award type: all ×`, `funding type: supplemental ×`) and the URL updates.
  - Dismiss one chip with `×` and verify the filter reverts; click `Clear filters` and verify all filters return to defaults (`award_type=grant`, `funding_type=all`, `category=""`, `recipient_type=all`).
  - Append `&mode=legacy&metric=old` to the URL and reload; verify unknown/legacy parameters are ignored and the page loads normally.
- [ ] **Budget category expansion & zero-hiding:** Expand `Federal accounts (N)` on a category bar (and switch `Show as table` / `Show as chart`) to verify nested account symbols and sums. Filter to `Funding type = Supplemental/emergency` and confirm categories with `$0` regular and `$0` supplemental are hidden.
- [ ] **CSV download:** Click `Download CSV` on `/cdc-funding/state/WY` (default FY2026 grants). Verify:
  - Filename is `chip-cdc-funding-WY-FY2026.csv`.
  - Line 1 starts with `# Source: USAspending · Award financial (File C), CDC · FY2026 P12 · CHIP build 7`.
  - Header contains `categories` and `accounts` alongside all award fields.
  - Data row count equals `42`, and `regular`, `supplemental`, `total` preserve exact cents.
- [ ] **Community state profile links (`/state/{fips}`):** Open each state profile and confirm both the `State funding profile` link and `Explore the {State} funding profile →` link navigate to `/cdc-funding/state/{CODE}`:
  - `/state/06` → `/cdc-funding/state/CA`
  - `/state/48` → `/cdc-funding/state/TX`
  - `/state/56` → `/cdc-funding/state/WY`
  - `/state/11` → `/cdc-funding/state/DC`
  - `/state/72` → `/cdc-funding/state/PR`

---

## State-by-State Walkthrough (FY2026)

### 1. California (`/cdc-funding/state/CA`, community link `/state/06`)

- [ ] **KPI totals (default `award_type=grant`):**
  - Total: **$276.0 million** (exact SQL: `$275,957,458.00`) · Regular: **$393.5 million** (`$393,477,480.14`) · Supplemental: **−$117.5 million** (`−$117,520,022.14`) · Awards/Grants: **294** · Recipients: **110**
- [ ] **Second line (`award_type=all`):**
  - Total: **$269.4 million** (exact SQL: `$269,431,206.59`) · Regular: **$454.6 million** (`$454,629,041.06`) · Supplemental: **−$185.2 million** (`−$185,197,834.47`) · Awards: **534** (294 grants, 240 contracts) · Recipients: **190**. Verify the contractor-location note appears.
- [ ] **Top 3 budget categories (grants, sorted by `abs(total)`):**
  1. **HIV/AIDS, Viral Hepatitis, STI and TB Prevention** (`HIV`): Regular `$117,367,081` (`$117,367,081.47`), Supplemental `$0`, Total `$117,367,081` (1 federal account)
  2. **Public Health Preparedness and Response** (`PHPR`): Regular `$53,315,238` (`$53,315,238.01`), Supplemental `$0`, Total `$53,315,238` (1 federal account)
  3. **Chronic Disease Prevention and Health Promotion** (`CHRONIC`): Regular `$43,638,008` (`$43,638,008.20`), Supplemental `$0`, Total `$43,638,008` (1 federal account)
- [ ] **First row sorted by amount (`Total ↕`, default `desc` by `abs(total)`):**
  - **Immunization and Vaccines for Children** (`NOFO title (Grants.gov)`) · Recipient: `PUBLIC HEALTH, CALIFORNIA DEPARTMENT OF` · FAIN `NH23IP922612` · NOFO `CDC-RFA-IP19-1901` · Regular `$0`, Supplemental `−$87,227,927` (`−$87,227,926.50`), Total `−$87,227,927` (`−$87,227,926.50`)
- [ ] **Search by FAIN:** Enter `NH23IP922612` (or `NU90TU000030`)
  - `NU90TU000030` → **1 award**, matching total `$44,448,956` (`$44,448,956.00`): *Public Health Emergency Preparedness (PHEP) Cooperative Agreement* (`PUBLIC HEALTH, CALIFORNIA DEPARTMENT OF`)
- [ ] **Search by NOFO:** Enter `CDC-RFA-IP19-1901`
  - Returns **1 award**, matching total `−$87,227,927` (`−$87,227,926.50`): *Immunization and Vaccines for Children* (`PUBLIC HEALTH, CALIFORNIA DEPARTMENT OF`)
- [ ] **Recipient type = State government (with default `award_type=grant`):**
  - Total: **$81.0 million** (`$81,015,701.68`) · Regular: **$199.3 million** (`$199,305,691.81`) · Supplemental: **−$118.3 million** (`−$118,289,990.13`) · Awards: **67** · Recipients: **16**
  - First row remains `NH23IP922612` (`PUBLIC HEALTH, CALIFORNIA DEPARTMENT OF`, `−$87,227,927`), carrying the `State government` label. Note: USAspending records `STATE GOVERNMENT` on prime transactions for several directly-funded local health departments (e.g., County of Los Angeles, City & County of San Francisco), so 16 recipients appear.

---

### 2. Texas (`/cdc-funding/state/TX`, community link `/state/48`)

- [ ] **KPI totals (default `award_type=grant`):**
  - Total: **$103.9 million** (exact SQL: `$103,855,574.34`) · Regular: **$231.3 million** (`$231,293,527.61`) · Supplemental: **−$127.4 million** (`−$127,437,953.27`) · Awards/Grants: **188** · Recipients: **73**
- [ ] **Second line (`award_type=all`):**
  - Total: **$163.2 million** (exact SQL: `$163,166,788.37`) · Regular: **$290.7 million** (`$290,693,132.76`) · Supplemental: **−$127.5 million** (`−$127,526,344.39`) · Awards: **290** (188 grants, 102 contracts) · Recipients: **111**. Verify the contractor-location note appears.
- [ ] **Top 3 budget categories (grants, sorted by `abs(total)`):**
  1. **HIV/AIDS, Viral Hepatitis, STI and TB Prevention** (`HIV`): Regular `$72,972,128` (`$72,972,128.39`), Supplemental `$0`, Total `$72,972,128` (1 federal account)
  2. **Public Health and Social Services Emergency Fund (HHS)** (`PHSSEF`, shows *"Outside CDC's operating plan"*): Regular `$0`, Supplemental `−$71,048,614` (`−$71,048,614.34`), Total `−$71,048,614` — verify supplemental bar extends **left** of the zero line (1 federal account)
  3. **Public Health Preparedness and Response** (`PHPR`): Regular `$42,915,264` (`$42,915,264.00`), Supplemental `$0`, Total `$42,915,264` (1 federal account)
- [ ] **First row sorted by amount (`Total ↕`, default `desc` by `abs(total)`):**
  - **2019 Epidemiology and Laboratory Capacity for Prevention and Control of Emerging Infectious Diseases (ELC)** (`NOFO title (Grants.gov)`) · Recipient: `DEPARTMENT OF STATE HEALTH SERVICES` · FAIN `NU50CK000501` · NOFO `CDC-RFA-CK19-1904` · Regular `$0`, Supplemental `−$68,578,806` (`−$68,578,805.62`), Total `−$68,578,806` (`−$68,578,805.62`)
- [ ] **Search by FAIN:** Enter `NU90TU000053`
  - Returns **1 award**, matching total `$42,915,264` (`$42,915,264.00`): *Public Health Emergency Preparedness (PHEP) Cooperative Agreement* (`DEPARTMENT OF STATE HEALTH SERVICES`)
- [ ] **Search by NOFO:** Enter `CDC-RFA-CK19-1904`
  - Returns **2 awards**, matching total `−$71,635,921` (`−$71,635,920.79`); top row is `NU50CK000501` (`DEPARTMENT OF STATE HEALTH SERVICES`)
- [ ] **Recipient type = State government (with default `award_type=grant`):**
  - Total: **$36.7 million** (`$36,658,113.03`) · Regular: **$164.5 million** (`$164,528,141.52`) · Supplemental: **−$127.9 million** (`−$127,870,028.49`) · Awards: **56** · Recipients: **10**
  - First row is `NU50CK000501` (`DEPARTMENT OF STATE HEALTH SERVICES`, `−$68,578,806`). Every visible row shows the `State government` label (per USAspending business types, which also include City of Houston and several Texas counties).

---

### 3. Wyoming (`/cdc-funding/state/WY`, community link `/state/56`)

- [ ] **KPI totals (default `award_type=grant`):**
  - Total: **−$2.7 million** (exact SQL: `−$2,722,018.25`) · Regular: **$19.2 million** (`$19,216,461.84`) · Supplemental: **−$21.9 million** (`−$21,938,480.09`) · Awards/Grants: **42** · Recipients: **11**
  - Good test for net-negative state total and negative supplemental KPI formatting (`−` sign on both Total and Supplemental).
- [ ] **Second line (`award_type=all`):**
  - Total: **−$2.4 million** (exact SQL: `−$2,443,071.25`) · Regular: **$19.5 million** (`$19,495,408.84`) · Supplemental: **−$21.9 million** (`−$21,938,480.09`) · Awards: **52** (42 grants, 10 contracts) · Recipients: **12**. Verify the contractor-location note appears.
- [ ] **Top 3 budget categories (grants, sorted by `abs(total)`):**
  1. **Cross-Cutting Activities and Program Support** (`CROSS`): Regular `$1,967,064` (`$1,967,063.59`), Supplemental `−$18,593,817` (`−$18,593,816.66`), Total `−$16,626,753` (`−$16,626,753.07`) — verify diverging regular (right) and supplemental (left) bars (1 federal account)
  2. **Chronic Disease Prevention and Health Promotion** (`CHRONIC`): Regular `$6,565,718` (`$6,565,718.00`), Supplemental `$0`, Total `$6,565,718` (1 federal account)
  3. **Public Health and Social Services Emergency Fund (HHS)** (`PHSSEF`, shows *"Outside CDC's operating plan"*): Regular `$0`, Supplemental `−$3,256,006` (`−$3,256,006.14`), Total `−$3,256,006` (1 federal account)
- [ ] **First row sorted by amount (`Total ↕`, default `desc` by `abs(total)`):**
  - **Immunization and Vaccines for Children** (`NOFO title (Grants.gov)`) · Recipient: `DEPARTMENT OF HEALTH WYOMING` · FAIN `NH23IP922577` · NOFO `CDC-RFA-IP19-1901` · Regular `−$1,560,560` (`−$1,560,559.74`), Supplemental `−$18,649,057` (`−$18,649,057.17`), Total `−$20,209,617` (`−$20,209,616.91`)
- [ ] **Search by FAIN:** Enter `NU90TU000049`
  - Returns **1 award**, matching total `$5,202,138` (`$5,202,138.00`): *Public Health Emergency Preparedness (PHEP) Cooperative Agreement* (`DEPARTMENT OF HEALTH WYOMING`)
- [ ] **Search by NOFO:** Enter `CDC-RFA-IP19-1901`
  - Returns **1 award**, matching total `−$20,209,617` (`−$20,209,616.91`): *Immunization and Vaccines for Children* (`DEPARTMENT OF HEALTH WYOMING`)
- [ ] **Recipient type = State government (with default `award_type=grant`):**
  - Total: **−$3.9 million** (`−$3,932,018.25`) · Regular: **$18.0 million** (`$18,006,461.84`) · Supplemental: **−$21.9 million** (`−$21,938,480.09`) · Awards: **32** · Recipients: **1** (`DEPARTMENT OF HEALTH WYOMING`)
  - First row is `NH23IP922577` (`−$20,209,617`), and every row belongs to `DEPARTMENT OF HEALTH WYOMING` with the `State government` label.

---

### 4. District of Columbia (`/cdc-funding/state/DC`, community link `/state/11`)

- [ ] **KPI totals (default `award_type=grant`):**
  - Total: **$157.4 million** (exact SQL: `$157,384,112.69`) · Regular: **$166.4 million** (`$166,403,922.79`) · Supplemental: **−$9.0 million** (`−$9,019,810.10`) · Awards/Grants: **128** · Recipients: **54**
- [ ] **Second line (`award_type=all`):**
  - Total: **$237.6 million** (exact SQL: `$237,612,970.29`) · Regular: **$248.7 million** (`$248,748,195.63`) · Supplemental: **−$11.1 million** (`−$11,135,225.34`) · Awards: **207** (128 grants, 79 contracts) · Recipients: **76**. Verify the contractor-location note appears.
- [ ] **Top 3 budget categories (grants, sorted by `abs(total)`):**
  1. **HIV/AIDS, Viral Hepatitis, STI and TB Prevention** (`HIV`): Regular `$38,315,972` (`$38,315,971.77`), Supplemental `$0`, Total `$38,315,972` (1 federal account)
  2. **Injury Prevention and Control** (`INJURY`): Regular `$24,676,453` (`$24,676,452.88`), Supplemental `$0`, Total `$24,676,453` (1 federal account)
  3. **Global Health** (`GLOBAL`): Regular `$20,746,023` (`$20,746,022.81`), Supplemental `$0`, Total `$20,746,023` (1 federal account)
- [ ] **First row sorted by amount (`Total ↕`, default `desc` by `abs(total)`):**
  - **Strengthening Public Health Systems and Services through National Partnerships to Improve and Protect the Nation's Health** (`NOFO title (Grants.gov)`) · Recipient: `NATIONAL ASSOCIATION OF COUNTY AND CITY HEALTH OFFICIALS` · FAIN `NU38PW000037` · NOFO `CDC-RFA-PW-24-0080` · Regular `$19,098,540` (`$19,098,540.00`), Supplemental `$0`, Total `$19,098,540` (`$19,098,540.00`). Expand this row to confirm multi-category/multi-account display (14 budget categories).
- [ ] **Search by FAIN:** Enter `NU27DD000021`
  - Returns **1 award**, matching total `$18,860,000` (`$18,860,000.00`): *Improving Health of Americans with Intellectual and Developmental Disabilities Through Evidence-Based Health Promotion Programs* (`SPECIAL OLYMPICS INC.`)
- [ ] **Search by NOFO:** Enter `CDC-RFA-PW-24-0080`
  - Returns **10 awards**, matching total `$38,049,761` (`$38,049,761.00`); top row is `NU38PW000037` (`NATIONAL ASSOCIATION OF COUNTY AND CITY HEALTH OFFICIALS`)
- [ ] **Recipient type = State government (with default `award_type=grant`):**
  - Total: **$36.5 million** (`$36,529,231.39`) · Regular: **$36.5 million** (`$36,529,231.39`) · Supplemental: **$0.0** (`$0.00`) · Awards: **29** · Recipients: **3**
  - First row changes from NACCHO to `NU62PS924847` (*High-Impact HIV Prevention and Surveillance Programs for Health Departments*, `DISTRICT OF COLUMBIA, GOVERNMENT OF`, `$9,716,524`). National NGOs (NACCHO, Special Olympics, etc.) are filtered out.

---

### 5. Puerto Rico (`/cdc-funding/state/PR`, community link `/state/72`)

- [ ] **KPI totals (default `award_type=grant`):**
  - Total: **$23.4 million** (exact SQL: `$23,371,719.64`) · Regular: **$42.4 million** (`$42,362,727.16`) · Supplemental: **−$19.0 million** (`−$18,991,007.52`) · Awards/Grants: **68** · Recipients: **24**
- [ ] **Second line (`award_type=all`):**
  - Total: **$23.5 million** (exact SQL: `$23,507,950.29`) · Regular: **$42.5 million** (`$42,508,205.84`) · Supplemental: **−$19.0 million** (`−$19,000,255.55`) · Awards: **79** (68 grants, 11 contracts) · Recipients: **31**. Verify the contractor-location note appears.
- [ ] **Top 3 budget categories (grants, sorted by `abs(total)`):**
  1. **HIV/AIDS, Viral Hepatitis, STI and TB Prevention** (`HIV`): Regular `$13,783,807` (`$13,783,806.62`), Supplemental `$0`, Total `$13,783,807` (1 federal account)
  2. **Cross-Cutting Activities and Program Support** (`CROSS`): Regular `$6,587,143` (`$6,587,143.44`), Supplemental `−$18,784,229` (`−$18,784,229.35`), Total `−$12,197,086` (`−$12,197,085.91`) — verify diverging regular (right) and supplemental (left) bars (1 federal account)
  3. **Public Health Preparedness and Response** (`PHPR`): Regular `$5,007,613` (`$5,007,613.34`), Supplemental `$0`, Total `$5,007,613` (1 federal account)
- [ ] **First row sorted by amount (`Total ↕`, default `desc` by `abs(total)`):**
  - **Immunization and Vaccines for Children** (`NOFO title (Grants.gov)`) · Recipient: `PUERTO RICO DEPARTMENT OF HEALTH` · FAIN `NH23IP922608` · NOFO `CDC-RFA-IP19-1901` · Regular `−$1,709,981` (`−$1,709,980.50`), Supplemental `−$18,784,229` (`−$18,784,229.35`), Total `−$20,494,210` (`−$20,494,209.85`)
- [ ] **Search by FAIN:** Enter `NU62PS924797`
  - Returns **1 award**, matching total `$10,425,425` (`$10,425,425.00`): *High-Impact HIV Prevention and Surveillance Programs for Health Departments* (`PUERTO RICO DEPARTMENT OF HEALTH`)
- [ ] **Search by NOFO:** Enter `CDC-RFA-IP19-1901`
  - Returns **1 award**, matching total `−$20,494,210` (`−$20,494,209.85`): *Immunization and Vaccines for Children* (`PUERTO RICO DEPARTMENT OF HEALTH`)
- [ ] **Recipient type = State government (with default `award_type=grant`):**
  - Total: **$9.1 million** (`$9,081,435.97`) · Regular: **$28.1 million** (`$28,072,443.49`) · Supplemental: **−$19.0 million** (`−$18,991,007.52`) · Awards: **36** · Recipients: **5**
  - First row is `NH23IP922608` (`PUERTO RICO DEPARTMENT OF HEALTH`, `−$20,494,210`). Verify Commonwealth agencies (e.g., Puerto Rico Department of Health, Department of Education of Puerto Rico) appear with the `State government` label.
