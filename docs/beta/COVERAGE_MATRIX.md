# Coverage matrix: what CHIP can answer today

Written 2026-11-14 from the product registries in `backend/app/area_pilot/registry/` and a read-only check of the live active releases. "Released" means a shared product with a pinned, published release, read through `app.area_pilot.lookup`. "Legacy" means an older import with no release pointer; it may be shown only in the profile's separate "Additional context" section with its vintage.

Levels: S = state, C = county, T = tract. Counts are of 2024 county equivalents (3,222 including Puerto Rico).

## Released measures (28 across seven products)

| Product (release) | Measure | Period | Levels | Uncertainty |
|---|---|---|---|---|
| CDC PLACES 2025 | Visited dentist in the past year | 2022 | C, T | 95% interval |
| | Current lack of health insurance, adults 18–64 | 2023 | C, T | 95% interval |
| Census ACS 5-year 2020–2024 | Median household income | 2020–2024 | S, C, T | 90% margin |
| HRSA AHRF 2024–2025 | Primary care physicians; dentists; psychiatrists; hospitals; hospital beds (counts) | 2023 | C | none |
| AHRQ CLH v2.0 | Households with broadband; housing units without a vehicle; renter cost burden | 2019–2023 | C, T | none |
| | Grocery stores per 1,000; fitness centers per 1,000 | 2023 | C | none |
| CMS Original Medicare GV | Beneficiaries; standardized payment per beneficiary; inpatient stays per 1,000; ER visits per 1,000; 30-day readmission rate | 2024 | S, C (+ national reference) | none |
| EPA AirData annual AQI | Median, 90th percentile, and maximum AQI; days with AQI; good days | 2025 | C (975 counties have a monitor) | none |
| USDA Food Environment Atlas | Low-income low-access share; SNAP stores per 1,000; WIC stores per 1,000; farmers' markets per 1,000; no-car low-access housing units | 2018–2023 by measure | C | none |

Facility inventories (released point products): HRSA health center sites (19,200 mapped), CMS nursing homes (13,878 mapped), EPA TRI reporting facilities (21,482 mapped).

586 counties outside Connecticut and Puerto Rico have a published value for all 28 measures. EPA AQI is the limiting product.

## User questions against coverage

| Profile section / question | Released today | Gap for the beta | Filled by |
|---|---|---|---|
| **Who lives here?** | Median household income (S, C, T) | Population, age structure, poverty, disability, language | C2 |
| **Major health conditions** | None (the two PLACES measures are access measures) | Chronic disease prevalence, mental health, risk behaviours | C1 |
| **Prevention and access barriers** | Dental visits, uninsured adults 18–64 (PLACES); no vehicle, broadband (CLH) | Routine checkup; all-ages uninsured rate | C1, C2 |
| **Healthcare workforce and facilities** | AHRF counts (C); health center sites; nursing homes | Per-population workforce rates need a published population denominator: show counts beside ACS population, do not divide unless the source publishes the rate. HPSA is legacy only. | C2 for population; HPSA stays "Additional context" |
| **Community conditions** | Income; renter cost burden; broadband; no vehicle | Poverty, disability, language | C2 |
| **Food and nutrition** | Five USDA measures; grocery stores per 1,000 (CLH) | None for the beta. Tract-level food access is legacy (2019, 2010 tracts) and stays out. | — |
| **Environment** | Annual AQI (975 counties); TRI reporting facilities | Heat and other indicators are out of scope for this beta | — |
| **Medicare use and spending** | Five CMS measures (S, C, national reference) | None | — |
| **Public-health funding** | CDC funding pages (state level, own methodology) | No county-level released product; profile links to the state funding profile, labelled state-level | X2 link only |
| **Vulnerability and hazards** | None released | SVI 2022, FEMA NRI are legacy | "Additional context" section |
| **Within-county patterns** | PLACES (2), ACS income, CLH (3) at tract level | More tract measures | C1, C2 |
| **State benchmark** | ACS income; CMS (5) | PLACES publishes no state estimate: none is shown. ACS additions include state. | C2 |
| **Congressional district** | Nothing | Boundaries, ACS district estimates, facilities in district, intersecting counties | C3 |
| **Outcomes (mortality)** | Nothing | Out of this beta by decision | later |

## Measure lists fixed for C1 and C2

These are the targets. Each is confirmed against the source release (name, data year, availability by level) inside its work package before it is added; a measure that fails the check is dropped and recorded, not substituted silently.

**C1, CDC PLACES 2025 (county and tract, crude prevalence with 95% interval), 11 additions:**

| Group | Measures |
|---|---|
| Health outcomes | Diagnosed diabetes; high blood pressure; obesity; coronary heart disease; stroke; COPD; current asthma; depression |
| Health status | Frequent mental distress |
| Risk behaviour | Current cigarette smoking |
| Prevention | Routine checkup in the past year |

PLACES measures come from different BRFSS years (high blood pressure is asked in alternate years). The period is recorded per measure. Kentucky and Pennsylvania gaps for 2023 measures, already documented for the insurance measure, are expected to apply to others.

**C2, Census ACS 5-year 2020–2024 (state, county, tract; source-published percentages with 90% margins), 7 additions:**

| Measure | Planned table |
|---|---|
| Total population | B01003 |
| People below the poverty level, percent | S1701 |
| Population aged 65 and over, percent | S0101 |
| Population under 18, percent | S0101 |
| People with a disability, percent | S1810 |
| People without health insurance, percent | S2701 |
| People who speak English less than "very well", percent | S1601 |

Subject tables are used so the percentage and its margin of error are the Census Bureau's own, not computed by CHIP.

After C1 and C2 the profile has 46 released measures: 13 PLACES, 8 ACS, and the 25 others above.

## Showcase places

Chosen from the 586 full-coverage counties, requiring at least three health center sites, two nursing homes, and three TRI reporting facilities, and aiming for contrast in size and region. Coverage is rechecked after C1 and C2.

| County | GEOID | Why |
|---|---|---|
| Person County, North Carolina | 37145 | Small and rural: 7 tracts; 4 health center sites, 2 nursing homes, 6 TRI reporting facilities |
| Kanawha County, West Virginia | 54039 | Mid-size, Appalachian (Charleston): 57 tracts; 36 health center sites, 9 nursing homes, 18 TRI reporting facilities |
| Fresno County, California | 06019 | Large and mixed urban/agricultural: 225 tracts; 111 health center sites, 30 nursing homes, 33 TRI reporting facilities |

The congressional district is chosen in C3 from districts that contain one of these counties.

## Known gaps that the beta will state, not hide

- Connecticut: several sources still publish the eight former counties; values are not shown on planning regions.
- Puerto Rico: outside PLACES, USDA, and CMS county coverage.
- EPA AQI: two thirds of counties have no monitor and show "no value reported".
- AHRF redistribution terms are unsettled (handbook priority); the product stays behind the access code.
- CLH's source endpoint returned empty responses at its last re-fetch; the published release is unaffected.
