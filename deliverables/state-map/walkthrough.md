# CDC State Funding Map — Staging Walkthrough Checklist

Generated from read-only SQL and the `/state-funding/v1/map` backend against `places_staging`, **CHIP build 7** (`state-funding-v1`, period **FY2026 P12**).

**Formatting & scope rules (Contract §3 + Amendments 1–2):**
- **Grants only:** The map shows CDC grant obligations (`award_type=grant`) to recipients in each state. Contracts are not included, and no ranks, shares, or per-capita values appear anywhere.
- **Formatting:** Whole dollars in tooltips, click panel, and table; compact dollars in legend ranges. Negative values use minus `−` (U+2212); positive values carry no `+`.
- **Source line:** `Source: USAspending · Award financial (File C), CDC · FY2026 P12 · CHIP build 7` (with the selected fiscal year's period).

---

## 1. Initial Load & Entry Links (`/cdc-funding/map`)

- [ ] **Links into the map:** Open `/cdc-funding` and `/cdc-funding/state/CA`; verify both show a **National map** link near the page title that navigates to `/cdc-funding/map`.
- [ ] **Header & default state (FY2026 · All categories · All funding):**
  - Eyebrow: `CDC funding · National map`
  - Title: `CDC grants to recipients by state`
  - Subtitle shows `FY2026` and `FY2026 P12` (no `· Deobligations excluded`).
  - Controls sit in one row on desktop: **Fiscal year** (`FY2026`), **Budget category** (`All categories`), **Funding type** (`All funding`), and **Exclude deobligations** (unchecked).
- [ ] **National summary & notes below the map:**
  - National total: **$2,903,439,520** (exact: `$2,903,439,520.38`) in **5,963 grants**.
  - Unattributed note: **`$152,619,342 in 330 grants has no recipient state and is not mapped.`** (exact: `$152,619,342.02`).
  - Notes show both the negative-supplemental explanation and: *"Grants are counted in the state of the recipient's address. Money a recipient passes on to sub-recipients in other states is not moved."*
  - Citation: `Source: USAspending · Award financial (File C), CDC · FY2026 P12 · CHIP build 7`.
- [ ] **Diverging color scale & legend:**
  - Positive states use 5 blue quantile classes ending in navy (`--chip-navy` / `--pdo-primary`).
  - Negative states (5 in FY2026 all funding: GA, ND, PA, OK, WY) use peach/orange classes labeled **Net reduction** in the legend, with compact dollar ranges.
  - Puerto Rico appears in its inset next to Hawaii, and the 6 tiles under the map (`DC`, `PR`, `GU`, `VI`, `AS`, `MP`) match the map's color classes. (`FM`, `MH`, and `PW` have no FY2026 grants, so they show no tiles in FY2026.)
  - Confirm no legend class repeats identical rounded bounds (for example, no `$X to $X` range; single-value classes display that single value alone).
- [ ] **Anonymous API auth gate (401):** Without a staging session cookie, confirm `GET /api/state-funding/v1/map` and `GET /api/state-funding/v1/map/shapes` both return HTTP **401**.

---

## 2. Dropdown Controls & URL State

- [ ] **Fiscal year dropdown:**
  - Switch to **FY2025**: URL updates to `?fy=2025`. National total updates to **$1,929,721,705** (`$1,929,721,705.40`) in **6,497 grants**; unattributed **$154,293,003** in **274 grants**; **16** states are net negative (led by Texas at `−$776,369,760`).
  - Switch to **FY2021**: URL updates to `?fy=2021`. National total updates to **$47,554,248,694** (`$47,554,248,693.68`) in **5,620 grants**; unattributed **$397,909,161** in **345 grants**; **0** negative states, so the **Net reduction** legend classes disappear.
  - Switch back to **FY2026** and reload to confirm URL state persists.
- [ ] **Budget category dropdown (in FY2026):**
  - Switch to **HIV/AIDS, Viral Hepatitis, STI and TB Prevention** (`category=HIV`):
    - National total **$931,322,775** (`$931,322,775.35`) in **832 grants**; unattributed **$2,569,993** in **8 grants**.
    - All 56 states/territories are positive (no **Net reduction** legend classes). California leads at **$117,367,081** (78 grants); American Samoa (`$431,378`), Northern Mariana Islands (`$656,699`), and Guam (`$1,015,140`) each have **1 grant**.
  - Switch to **Public Health Preparedness and Response** (`category=PHPR`):
    - National total **$561,809,277** (`$561,809,276.70`) in **158 grants**; unattributed **$374,497** in **6 grants**.
    - California leads at **$53,315,238** (7 grants); **Guam** is net negative at **−$179,821** (2 grants) and shades in peach/orange.
  - Reset to **All categories**.
- [ ] **Funding type dropdown (in FY2026 · All categories):**
  - Switch to **Regular** (`funding_type=regular`):
    - National total **$4,989,433,905** (`$4,989,433,904.72`) in **5,651 grants**; unattributed **$138,230,585** in **313 grants**.
    - **0** negative states; **Net reduction** legend classes and the negative-supplemental note disappear. Top 3: California (`$393,477,480`), New York (`$340,659,892`), Georgia (`$305,287,301`).
  - Switch to **Supplemental** (`funding_type=supplemental`):
    - National total **−$2,085,994,384** (`−$2,085,994,384.34`) in **862 grants**; unattributed **$14,388,757** in **75 grants**.
    - **55 of 56** mapped/tile areas are net negative (peach/orange), with only **Northern Mariana Islands (`MP`)** positive at **$1,765,772** (5 grants). Georgia is most negative at **−$330,162,801** (27 grants).
  - Reset to **All funding**.

---

## 3. "Exclude deobligations" Check Box (Amendment 1)

- [ ] **Toggle on (FY2026 · All categories · All funding):**
  - Check **Exclude deobligations**. Confirm URL updates to include `deobligations=exclude`.
  - Confirm subtitle appends **`· Deobligations excluded`**.
  - Confirm national total increases from `$2,903,439,520` (5,963 grants) to **$5,520,499,201** (`$5,520,499,200.60`) in **4,261 grants**; unattributed updates to **$172,235,453** (`$172,235,453.36`) in **187 grants**.
  - Confirm the exclusion note appears: *"Deobligations (net reductions for an award in this year) are left out, so totals show new and added obligations only."* and the negative-supplemental note disappears.
  - Confirm all 56 states/territories are positive and the legend hides the **Net reduction** classes.
  - Spot-check state changes: California rises from `$275,957,458` (294 grants) to **$414,790,905** (214 grants); Georgia flips from `−$24,875,500` (193 grants) to **$333,350,403** (143 grants).
- [ ] **Supplemental + Exclude deobligations (gray "No grants" states):**
  - Keep **Exclude deobligations** checked and set **Funding type** to **Supplemental**.
  - Confirm national total is **$87,340,264** (`$87,340,263.72`) in **77 grants**; unattributed **$25,795,000** in **18 grants**.
  - Confirm **36** states/territories are shaded blue (Maryland highest at **$14,909,210**, 6 grants) and the remaining **20** states/territories (for example Puerto Rico, Guam, Vermont) render light gray with **"No grants"** in the tooltip.
- [ ] **Panel disclaimer & link check while checked:**
  - Switch back to **All funding** with **Exclude deobligations** still checked and click **California**.
  - Confirm California's panel shows Total **$414,790,905**, Regular **$413,607,176**, Supplemental **$1,183,729**, **214 grants**, **91 recipients**, and top category `HIV/AIDS, Viral Hepatitis, STI and TB Prevention` (`$123,580,499`).
  - Confirm the line under the panel links reads: **`The state funding profile shows net amounts, including deobligations.`**
  - Confirm the **State funding profile** link points to `/cdc-funding/state/CA?fy=2026&funding_type=all&award_type=grant` (it does **not** carry `deobligations=exclude`).
- [ ] Uncheck **Exclude deobligations** and confirm the map returns to default net totals (`$2,903,439,520`).

---

## 4. Tooltip (Hover & Keyboard Focus)

- [ ] **Hover tooltip (FY2026 · All categories · All funding):** Hover California → displays **`California`**, **`$275,957,458`**, and **`294 grants`**.
- [ ] **Keyboard focus tooltip:** Tab onto a state shape or territory tile → tooltip appears for the focused area without a mouse.
- [ ] **Singular `"1 grant"` grammar:** Switch to Budget category = `HIV` and hover the **Guam** or **American Samoa** tile (or under `Supplemental` + `Exclude deobligations`, hover **Alabama** `$75,000` or **DC** `$75,000`) → confirm the tooltip reads **`1 grant`** (not `1 grants`).
- [ ] **`"No grants"` tooltip:** Under `Supplemental` + `Exclude deobligations`, hover a light-gray state (e.g., **Puerto Rico** or **Guam**) → tooltip labels it **`No grants`**.

---

## 5. California Panel & Both Links (FY2026 · All categories · All funding)

- [ ] **Open panel:** Click California (or press `Enter` while focused). Confirm URL adds `state=CA`.
- [ ] **Header & figures:**
  - Title: **California** · Filter summary: **`FY2026 · All categories · All funding`**
  - Total: **$275,957,458** (`$275,957,458.00`) · Regular: **$393,477,480** (`$393,477,480.14`) · Supplemental: **−$117,520,022** (`−$117,520,022.14`)
  - Grants: **294** · Recipients: **110**
- [ ] **Top 5 budget categories (sorted by `abs(total)`):**
  1. HIV/AIDS, Viral Hepatitis, STI and TB Prevention: **$117,367,081**
  2. Public Health Preparedness and Response: **$53,315,238**
  3. Chronic Disease Prevention and Health Promotion: **$43,638,008**
  4. Cross-Cutting Activities and Program Support: **−$42,450,019**
  5. Immunization and Respiratory Diseases: **$37,046,818**
  - *(Verify that when a single Budget category is selected in the dropdown, this top-5 category breakdown is omitted.)*
- [ ] **Link 1 — State indicators:** Click **State indicators** → navigates to `/community/state/06` and loads California's community indicators profile. Navigate back.
- [ ] **Link 2 — State funding profile:** Click **State funding profile** → navigates to `/cdc-funding/state/CA?fy=2026&funding_type=all&award_type=grant` (also confirm that selecting a non-default filter such as `FY2025` or `Regular` or `HIV` carries those parameters in the link URL). Navigate back.
- [ ] **Dismiss panel:** Close with the **Close** button and again with the **`Escape`** key; confirm `state=CA` is removed from the URL.

---

## 6. Negative State — Georgia (FY2026 · All funding)

- [ ] **Map shading & tooltip:** Locate Georgia in the peach/orange **Net reduction** shading (alongside ND `−$10,926,633`, PA `−$6,190,216`, OK `−$3,919,409`, WY `−$2,722,018`). Hover Georgia → **`Georgia`**, **`−$24,875,500`** (U+2212 minus), **`193 grants`**.
- [ ] **Panel figures:** Click Georgia and verify:
  - Total: **−$24,875,500** (`−$24,875,500.39`) · Regular: **$305,287,301** (`$305,287,300.80`) · Supplemental: **−$330,162,801** (`−$330,162,801.19`)
  - Grants: **193** · Recipients: **64**
  - Top 5 categories lead with **Public Health and Social Services Emergency Fund (HHS)** at **−$280,317,225**, followed by Chronic Disease (`$92,170,889`), HIV (`$46,019,112`), Global Health (`$44,352,517`), and Injury Prevention (`$31,698,000`).
  - Both **State indicators** (`/community/state/13`) and **State funding profile** (`/cdc-funding/state/GA?...`) links appear.

---

## 7. DC, Guam, and FY2023 Palau Tiles (Amendment 2)

- [ ] **DC tile (FY2026 · All funding):** Click the **DC** tile in the tile row below the map.
  - Panel shows **District of Columbia**: Total **$157,384,113** (`$157,384,112.69`) · Regular **$166,403,923** (`$166,403,922.79`) · Supplemental **−$9,019,810** (`−$9,019,810.10`) · **128 grants** · **54 recipients**.
  - Top category: `HIV/AIDS, Viral Hepatitis, STI and TB Prevention` (`$38,315,972`).
  - Confirm **both** links appear: **State indicators** (`/community/state/11`) and **State funding profile** (`/cdc-funding/state/DC?...`).
- [ ] **Guam tile (FY2026 · All funding):** Click the **GU** tile.
  - Panel shows **Guam**: Total **$2,149,983** (`$2,149,983.16`) · Regular **$5,703,541** (`$5,703,541.11`) · Supplemental **−$3,553,558** (`−$3,553,557.95`) · **24 grants** · **5 recipients**.
  - Top category by `abs(total)`: `Cross-Cutting Activities and Program Support` (`−$2,403,978`).
  - Confirm **State funding profile** (`/cdc-funding/state/GU?...`) appears and **State indicators** is **omitted** (likewise omitted for `VI`, `AS`, `MP`; present for `PR` at `/community/state/72`).
- [ ] **Palau tile (`PW`) in FY2023 (Freely Associated States, Amendment 2):**
  - Switch **Fiscal year** to **FY2023** (All categories · All funding; period `FY2023 P12`). Confirm the tile row under the map expands to **9** tiles in order: **`DC`, `PR`, `GU`, `VI`, `AS`, `MP`, `FM`, `MH`, `PW`** (and returns to 6 tiles when switched back to FY2026, because `FM`, `MH`, and `PW` have no FY2026 grants).
  - Hover the **PW** tile → tooltip shows **`Palau`**, **`$13,098,676`**, and **`17 grants`**.
  - Click the **PW** tile → URL updates to include `fy=2023` and `state=PW`.
  - Panel shows **Palau** (`FY2023 · All categories · All funding`): Total **$13,098,676** (`$13,098,676.05`) · Regular **$2,676,004** (`$2,676,004.05`) · Supplemental **$10,422,672** (`$10,422,672.00`) · **17 grants** · **1 recipient**.
  - Top 5 budget categories: `Public Health and Social Services Emergency Fund (HHS)` (`$8,266,049`), `Cross-Cutting Activities and Program Support` (`$2,396,947`), `Chronic Disease Prevention and Health Promotion` (`$1,057,961`), `HIV/AIDS, Viral Hepatitis, STI and TB Prevention` (`$416,906`), and `Public Health Preparedness and Response` (`$370,357`).
  - Confirm **State funding profile** points to `/cdc-funding/state/PW?fy=2023&funding_type=all&award_type=grant` and opens Palau's FY2023 state funding page; confirm **State indicators** is **omitted** (same for `FM` and `MH`).

---

## 8. Table of States (`<details>`)

- [ ] **Expand & row count:** Expand **Table of states** below the map. Confirm **56** rows in FY2026 (unattributed `'__'` is not in the table; it remains in the note above).
- [ ] **Sort by state name:**
  - Ascending: first 3 rows are **Alabama** (`$52,339,133`, 74 grants), **Alaska** (`$43,476,367`, 69 grants), **American Samoa** (`$3,791,237`, 17 grants); last row is **Wyoming** (`−$2,722,018`, 42 grants).
- [ ] **Sort by amount:**
  - Descending: top 3 are **California** (`$275,957,458`, 294 grants), **New York** (`$249,145,584`, 353 grants), **District of Columbia** (`$157,384,113`, 128 grants); bottom 3 are **Pennsylvania** (`−$6,190,216`), **North Dakota** (`−$10,926,633`), **Georgia** (`−$24,875,500`).
  - Ascending: **Georgia** (`−$24,875,500`) appears first.
- [ ] **Dollar alignment & wrapping:** Amounts stay on one line with no mid-number wrapping, and negative values use `−` (U+2212).

---

## 9. Phone Width (`375 × 812`) & Touch

- [ ] **No horizontal overflow:** Resize viewport to `375 × 812` and confirm `document.documentElement.scrollWidth <= 375` across default view, open panel, and expanded table.
- [ ] **Stacked controls & map fit:** Dropdowns and the **Exclude deobligations** check box stack cleanly; the SVG map, Puerto Rico inset, legend, and 6 territory tiles fit without clipping.
- [ ] **Bottom-sheet panel:** Tap California (or the Guam tile) → opens as a bottom sheet (no stuck hover tooltip), shows all figures and links cleanly, and closes cleanly with the Close button.
