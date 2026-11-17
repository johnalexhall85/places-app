# CHIP MCP Server Evaluation Report

- **Timestamp:** `2026-11-17T15:28:13.202233+00:00`
- **Commit:** `a0c55c1`
- **Mode:** `live-mcp`
- **Server URL:** `http://127.0.0.1:8011/mcp`
- **Questions Passed:** **31 / 44**
- **Total Tool Calls:** `65`
- **Latency p50:** `53.5 ms`
- **Latency p95:** `125.2 ms`

## Summary Table

| ID | Trap | Tools | Products | Levels | Latency (ms) | Result |
|---|---|---|---|---|---:|---|
| Q01 | No | `find_places`, `get_area_values` | `places` | `county` | 159.3 | PASS |
| Q02 | No | `find_places`, `find_places`, `get_area_values` | `places`, `acs_profile` | `county` | 154.6 | PASS |
| Q03 | No | `get_area_values` | `acs`, `clh` | `county` | 54.9 | PASS |
| Q04 | No | `get_area_values` | `usda_fea`, `clh` | `county` | 16.2 | PASS |
| Q05 | No | `get_area_values` | `epa_aqi` | `county` | 54.3 | PASS |
| Q06 | No | `find_places`, `get_area_values` | `brfss` | `state` | 102.3 | PASS |
| Q07 | No | `find_places`, `get_area_values` | `acs_profile` | `cd` | 98.9 | PASS |
| Q08 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 79.9 | PASS |
| Q09 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 47.2 | PASS |
| Q10 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 209.7 | PASS |
| Q11 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `cd` | 874.2 | PASS |
| Q12 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `state` | 73.5 | PASS |
| Q13 | No | `get_area_context`, `get_area_values` | `acs_profile` | `tract` | 98.6 | PASS |
| Q14 | No | `get_measure_across_areas` | `places` | `county` | 62.5 | **FAIL** |
| Q15 | No | `get_measure_across_areas` | `places` | `county` | 57.2 | **FAIL** |
| Q16 | No | `get_measure_across_areas` | `places` | `county` | 78.1 | **FAIL** |
| Q17 | No | `get_measure_across_areas` | `acs_profile` | `tract` | 84.5 | **FAIL** |
| Q18 | No | `get_measure_across_areas` | `places` | `tract` | 89.5 | **FAIL** |
| Q19 | No | `get_measure_across_areas` | `clh` | `tract` | 70.4 | **FAIL** |
| Q20 | No | `get_measure_across_areas` | `acs_profile` | `cd` | 54.1 | **FAIL** |
| Q21 | No | `get_measure_across_areas` | `acs` | `state` | 53.7 | **FAIL** |
| Q22 | No | `get_measure_across_areas` | `usda_fea` | `county` | 55.7 | **FAIL** |
| Q23 | No | `get_area_values` | `places`, `acs`, `acs_profile`, `clh` | `tract` | 56.3 | PASS |
| Q24 | No | `search_measures` | `places`, `acs`, `acs_profile`, `brfss`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea` | `state`, `county`, `tract`, `cd` | 52.7 | PASS |
| Q25 | No | `search_measures` | `places`, `acs_profile` | `county` | 51.4 | PASS |
| Q26 | No | `get_measure_details` | `places`, `acs_profile`, `brfss` | `state`, `county`, `tract`, `cd` | 52.5 | PASS |
| Q27 | No | `get_measure_details` | `cms_gv`, `usda_fea`, `epa_aqi`, `clh` | `state`, `county` | 51.7 | PASS |
| Q28 | No | `list_data_sources` | `places`, `acs`, `acs_profile`, `brfss`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea`, `health_centers`, `nursing_homes`, `tri_facilities` | `state`, `county`, `tract`, `cd` | 67.7 | PASS |
| Q29 | No | `find_places`, `find_places`, `find_places`, `find_places` | `places`, `acs_profile` | `state`, `county`, `cd` | 178.9 | PASS |
| Q30 | No | `find_places` | `places` | `county` | 47.9 | PASS |
| Q31 | No | `get_area_values` | `places`, `acs`, `acs_profile`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea` | `county` | 23.4 | PASS |
| Q32 | No | `get_area_values` | `acs`, `acs_profile`, `brfss`, `cms_gv` | `state` | 20.8 | PASS |
| Q33 | Yes (`ahrf_excluded`) | `search_measures`, `get_area_values` | `ahrf` | `county` | 101.4 | PASS |
| Q34 | Yes (`time_trend_one_period`) | `get_area_values`, `list_data_sources` | `places` | `county` | 96.8 | PASS |
| Q35 | Yes (`no_composite_score`) | `search_measures`, `get_measure_across_areas` | `places` | `county` | 67.3 | **FAIL** |
| Q36 | Yes (`epa_aqi_no_monitor`) | `get_area_values`, `get_measure_across_areas` | `epa_aqi` | `county` | 112.7 | **FAIL** |
| Q37 | Yes (`kentucky_brfss_not_published`) | `get_area_values`, `get_measure_across_areas` | `brfss` | `state` | 114.3 | **FAIL** |
| Q38 | Yes (`cms_not_published_for_cd`) | `get_measure_across_areas`, `get_area_values` | `cms_gv`, `acs_profile` | `cd` | 110.9 | PASS |
| Q39 | Yes (`tracts_require_county`) | `get_measure_across_areas`, `get_measure_across_areas` | `places` | `tract` | 85.5 | PASS |
| Q40 | Yes (`medicare_original_beneficiaries`) | `get_area_values` | `cms_gv` | `county` | 54.7 | PASS |
| Q41 | Yes (`ct_pr_coverage_status`) | `get_area_values` | `usda_fea`, `cms_gv` | `county` | 54.2 | PASS |
| Q42 | Yes (`limits_and_truncation`) | `get_area_values`, `get_measure_across_areas` | `acs`, `places` | `county`, `tract` | 187.7 | **FAIL** |
| Q43 | Yes (`ahrf_withheld_topic`) | `search_measures`, `get_area_values` | `ahrf` | `county` | 102.7 | PASS |
| Q44 | Yes (`ahrf_withheld_queries`) | `search_measures`, `search_measures`, `search_measures`, `search_measures` | `ahrf` | `county` | 202.8 | PASS |

## Failures

### Q14: List adult diagnosed diabetes prevalence (places:diabetes_crudeprev) across all 67 counties of Alabama in GEOID order.
- Call 0 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 0 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {'low': 11.4, 'high': 15.3}
- Call 0 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {'low': 11.5, 'high': 15.3}
- Call 0 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {'low': 17.3, 'high': 22.2}
- Call 0 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {'low': 14.0, 'high': 18.6}
- Call 0 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {'low': 11.8, 'high': 16.0}
- Call 0 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {'low': 21.9, 'high': 27.6}
- Call 0 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {'low': 16.5, 'high': 21.4}
- Call 0 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {'low': 12.9, 'high': 17.0}
- Call 0 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {'low': 15.7, 'high': 20.4}
- Call 0 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {'low': 13.7, 'high': 18.6}
- Call 0 (get_measure_across_areas): with_value[10]: Compact row missing uncertainty.kind: {'low': 12.1, 'high': 16.1}
- Call 0 (get_measure_across_areas): with_value[11]: Compact row missing uncertainty.kind: {'low': 17.7, 'high': 22.8}
- Call 0 (get_measure_across_areas): with_value[12]: Compact row missing uncertainty.kind: {'low': 16.1, 'high': 21.0}
- Call 0 (get_measure_across_areas): with_value[13]: Compact row missing uncertainty.kind: {'low': 14.0, 'high': 18.9}
- Call 0 (get_measure_across_areas): with_value[14]: Compact row missing uncertainty.kind: {'low': 12.2, 'high': 16.8}

### Q15: Which counties in Alabama have the highest point estimates of adult obesity (places:obesity_crudeprev), sorted descending?
- Call 0 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 0 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {'low': 44.5, 'high': 61.6}
- Call 0 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {'low': 43.8, 'high': 61.4}
- Call 0 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {'low': 42.5, 'high': 60.4}
- Call 0 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {'low': 41.4, 'high': 59.7}
- Call 0 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {'low': 42.3, 'high': 60.0}
- Call 0 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {'low': 39.6, 'high': 56.3}
- Call 0 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {'low': 38.9, 'high': 56.2}
- Call 0 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {'low': 38.5, 'high': 55.9}
- Call 0 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {'low': 38.5, 'high': 55.2}
- Call 0 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {'low': 38.0, 'high': 55.7}
- Call 0 (get_measure_across_areas): with_value[10]: Compact row missing uncertainty.kind: {'low': 37.6, 'high': 55.1}
- Call 0 (get_measure_across_areas): with_value[11]: Compact row missing uncertainty.kind: {'low': 38.4, 'high': 54.4}
- Call 0 (get_measure_across_areas): with_value[12]: Compact row missing uncertainty.kind: {'low': 40.1, 'high': 52.3}
- Call 0 (get_measure_across_areas): with_value[13]: Compact row missing uncertainty.kind: {'low': 38.1, 'high': 53.0}
- Call 0 (get_measure_across_areas): with_value[14]: Compact row missing uncertainty.kind: {'low': 36.2, 'high': 53.0}

### Q16: Show diagnosed diabetes prevalence (places:diabetes_crudeprev) across all 254 counties in Texas, including any county with no row in the published release.
- Call 0 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 0 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {'low': 20.7, 'high': 26.2}
- Call 0 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {'low': 20.9, 'high': 24.9}
- Call 0 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {'low': 20.8, 'high': 24.3}
- Call 0 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {'low': 19.4, 'high': 24.9}
- Call 0 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {'low': 18.3, 'high': 24.4}
- Call 0 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {'low': 18.1, 'high': 23.7}
- Call 0 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {'low': 18.2, 'high': 23.4}
- Call 0 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {'low': 17.6, 'high': 22.6}
- Call 0 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {'low': 18.1, 'high': 21.5}
- Call 0 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {'low': 16.7, 'high': 21.8}
- Call 0 (get_measure_across_areas): with_value[10]: Compact row missing uncertainty.kind: {'low': 16.6, 'high': 22.2}
- Call 0 (get_measure_across_areas): with_value[11]: Compact row missing uncertainty.kind: {'low': 16.3, 'high': 21.6}
- Call 0 (get_measure_across_areas): with_value[12]: Compact row missing uncertainty.kind: {'low': 16.6, 'high': 21.3}
- Call 0 (get_measure_across_areas): with_value[13]: Compact row missing uncertainty.kind: {'low': 16.3, 'high': 21.3}
- Call 0 (get_measure_across_areas): with_value[14]: Compact row missing uncertainty.kind: {'low': 16.4, 'high': 21.1}
- Call 0 (get_measure_across_areas): without_value[0]: Compact row missing uncertainty.kind: {'low': None, 'high': None}

### Q17: How does the poverty rate (acs_profile:poverty_pct) vary across the 7 census tracts of Person County, North Carolina (37145)?
- Call 0 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 0 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {'moe': 8.6}
- Call 0 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {'moe': 12.5}
- Call 0 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {'moe': 7.6}
- Call 0 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {'moe': 7.6}
- Call 0 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {'moe': 6.5}
- Call 0 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {'moe': 3.2}
- Call 0 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {'moe': 2.4}

### Q18: What is the tract-level distribution of current cigarette smoking (places:csmoking_crudeprev) across the 57 census tracts in Kanawha County, WV (54039)?
- Call 0 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 0 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {'low': 28.0, 'high': 37.7}
- Call 0 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {'low': 27.8, 'high': 36.6}
- Call 0 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {'low': 27.0, 'high': 35.9}
- Call 0 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {'low': 22.8, 'high': 30.7}
- Call 0 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {'low': 22.7, 'high': 29.5}
- Call 0 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {'low': 22.5, 'high': 28.4}
- Call 0 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {'low': 21.7, 'high': 28.6}
- Call 0 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {'low': 21.1, 'high': 28.7}
- Call 0 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {'low': 21.5, 'high': 27.8}
- Call 0 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {'low': 20.8, 'high': 28.3}
- Call 0 (get_measure_across_areas): with_value[10]: Compact row missing uncertainty.kind: {'low': 20.4, 'high': 28.1}
- Call 0 (get_measure_across_areas): with_value[11]: Compact row missing uncertainty.kind: {'low': 20.7, 'high': 27.8}
- Call 0 (get_measure_across_areas): with_value[12]: Compact row missing uncertainty.kind: {'low': 20.7, 'high': 27.1}
- Call 0 (get_measure_across_areas): with_value[13]: Compact row missing uncertainty.kind: {'low': 20.2, 'high': 27.2}
- Call 0 (get_measure_across_areas): with_value[14]: Compact row missing uncertainty.kind: {'low': 20.3, 'high': 27.1}

### Q19: List the top 25 census tracts in Fresno County, CA (06019) by percentage of occupied housing units without a vehicle (clh:ACS_PCT_HU_NO_VEH).
- Call 0 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 0 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[10]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[11]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[12]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[13]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[14]: Compact row missing uncertainty.kind: {}

### Q20: Compare the all-ages uninsured rate (acs_profile:uninsured_pct) across all 14 congressional districts in North Carolina.
- Call 0 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 0 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {'moe': 0.5}
- Call 0 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {'moe': 0.5}
- Call 0 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {'moe': 0.3}
- Call 0 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {'moe': 0.4}
- Call 0 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {'moe': 0.4}
- Call 0 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {'moe': 0.5}
- Call 0 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {'moe': 0.4}
- Call 0 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {'moe': 0.4}
- Call 0 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {'moe': 0.4}
- Call 0 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {'moe': 0.4}
- Call 0 (get_measure_across_areas): with_value[10]: Compact row missing uncertainty.kind: {'moe': 0.3}
- Call 0 (get_measure_across_areas): with_value[11]: Compact row missing uncertainty.kind: {'moe': 0.5}
- Call 0 (get_measure_across_areas): with_value[12]: Compact row missing uncertainty.kind: {'moe': 0.4}
- Call 0 (get_measure_across_areas): with_value[13]: Compact row missing uncertainty.kind: {'moe': 0.4}

### Q21: How does median household income (acs:B19013_001E) compare across all states, DC, and Puerto Rico, ordered from lowest to highest?
- Call 0 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 0 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {'moe': 261}
- Call 0 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {'moe': 539}
- Call 0 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {'moe': 691}
- Call 0 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {'moe': 408}
- Call 0 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {'moe': 467}
- Call 0 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {'moe': 429}
- Call 0 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {'moe': 399}
- Call 0 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {'moe': 808}
- Call 0 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {'moe': 439}
- Call 0 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {'moe': 570}
- Call 0 (get_measure_across_areas): with_value[10]: Compact row missing uncertainty.kind: {'moe': 429}
- Call 0 (get_measure_across_areas): with_value[11]: Compact row missing uncertainty.kind: {'moe': 325}
- Call 0 (get_measure_across_areas): with_value[12]: Compact row missing uncertainty.kind: {'moe': 321}
- Call 0 (get_measure_across_areas): with_value[13]: Compact row missing uncertainty.kind: {'moe': 352}
- Call 0 (get_measure_across_areas): with_value[14]: Compact row missing uncertainty.kind: {'moe': 324}

### Q22: List the counties of West Virginia by SNAP-authorized stores per 1,000 residents (usda_fea:snap_stores_per_1000).
- Call 0 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 0 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[10]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[11]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[12]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[13]: Compact row missing uncertainty.kind: {}
- Call 0 (get_measure_across_areas): with_value[14]: Compact row missing uncertainty.kind: {}

### Q35: Which county in Alabama is the healthiest overall based on a composite health score?
- Call 1 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 1 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {'low': 9.5, 'high': 12.9}
- Call 1 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {'low': 10.4, 'high': 13.7}
- Call 1 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {'low': 10.5, 'high': 14.0}
- Call 1 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {'low': 10.9, 'high': 14.4}
- Call 1 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {'low': 10.7, 'high': 14.3}
- Call 1 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {'low': 11.2, 'high': 14.9}
- Call 1 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {'low': 11.3, 'high': 15.0}
- Call 1 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {'low': 11.0, 'high': 15.2}
- Call 1 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {'low': 11.4, 'high': 15.3}
- Call 1 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {'low': 11.5, 'high': 15.3}

### Q36: What is the median AQI (epa_aqi:median_aqi) across Alabama counties, and what is reported for counties without an EPA air monitor such as Autauga County (01001)?
- Call 1 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 1 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[10]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[11]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[12]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[13]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): with_value[14]: Compact row missing uncertainty.kind: {}
- Call 1 (get_measure_across_areas): without_value[0]: Compact row missing uncertainty.kind: {}

### Q37: What is Kentucky's 2023 state BRFSS adult diabetes prevalence (brfss:diabetes), and how does get_measure_across_areas report Kentucky and Pennsylvania?
- Call 1 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 1 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {'low': 17.9, 'high': 21.6}
- Call 1 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {'low': 16.9, 'high': 19.5}
- Call 1 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {'low': 15.3, 'high': 18.6}
- Call 1 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {'low': 14, 'high': 19.2}
- Call 1 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {'low': 13.5, 'high': 19.2}
- Call 1 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {'low': 14.8, 'high': 17.3}
- Call 1 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {'low': 14.4, 'high': 17}
- Call 1 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {'low': 14, 'high': 15.8}
- Call 1 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {'low': 13.4, 'high': 15.7}
- Call 1 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {'low': 13.3, 'high': 15.8}
- Call 1 (get_measure_across_areas): with_value[10]: Compact row missing uncertainty.kind: {'low': 11.9, 'high': 14.8}
- Call 1 (get_measure_across_areas): with_value[11]: Compact row missing uncertainty.kind: {'low': 12.4, 'high': 13.9}
- Call 1 (get_measure_across_areas): with_value[12]: Compact row missing uncertainty.kind: {'low': 12.4, 'high': 13.9}
- Call 1 (get_measure_across_areas): with_value[13]: Compact row missing uncertainty.kind: {'low': 11.8, 'high': 13.7}
- Call 1 (get_measure_across_areas): with_value[14]: Compact row missing uncertainty.kind: {'low': 11.5, 'high': 13.9}
- Call 1 (get_measure_across_areas): without_value[0]: Compact row missing uncertainty.kind: {'low': None, 'high': None}

### Q42: What happens if I request all 41 county measures for 12 counties at once (492 rows, exceeding the 400-row cap), or request median household income across all 2,498 tracts of Los Angeles County (06037)?
- Call 1 (get_measure_across_areas): data.measure has unexpected extra keys: ['uncertainty_kind', 'uncertainty_label']
- Call 1 (get_measure_across_areas): with_value[0]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[1]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[2]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[3]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[4]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[5]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[6]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[7]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[8]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[9]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[10]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[11]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[12]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[13]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): with_value[14]: Compact row missing uncertainty.kind: {'moe': None}
- Call 1 (get_measure_across_areas): without_value[0]: Compact row missing uncertainty.kind: {'moe': None}

