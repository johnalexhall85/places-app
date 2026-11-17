# CHIP MCP Server Evaluation Report

- **Timestamp:** `2026-11-17T15:36:03.163214+00:00`
- **Commit:** `7db7f59`
- **Mode:** `live-mcp`
- **Server URL:** `http://127.0.0.1:8011/mcp`
- **Questions Passed:** **44 / 44**
- **Total Tool Calls:** `65`
- **Latency p50:** `53.2 ms`
- **Latency p95:** `125.3 ms`

## Summary Table

| ID | Trap | Tools | Products | Levels | Latency (ms) | Result |
|---|---|---|---|---|---:|---|
| Q01 | No | `find_places`, `get_area_values` | `places` | `county` | 147.8 | PASS |
| Q02 | No | `find_places`, `find_places`, `get_area_values` | `places`, `acs_profile` | `county` | 151.5 | PASS |
| Q03 | No | `get_area_values` | `acs`, `clh` | `county` | 54.4 | PASS |
| Q04 | No | `get_area_values` | `usda_fea`, `clh` | `county` | 15.6 | PASS |
| Q05 | No | `get_area_values` | `epa_aqi` | `county` | 53.5 | PASS |
| Q06 | No | `find_places`, `get_area_values` | `brfss` | `state` | 101.7 | PASS |
| Q07 | No | `find_places`, `get_area_values` | `acs_profile` | `cd` | 104.0 | PASS |
| Q08 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 65.9 | PASS |
| Q09 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 46.4 | PASS |
| Q10 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 208.1 | PASS |
| Q11 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `cd` | 859.8 | PASS |
| Q12 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `state` | 73.0 | PASS |
| Q13 | No | `get_area_context`, `get_area_values` | `acs_profile` | `tract` | 98.7 | PASS |
| Q14 | No | `get_measure_across_areas` | `places` | `county` | 59.6 | PASS |
| Q15 | No | `get_measure_across_areas` | `places` | `county` | 56.7 | PASS |
| Q16 | No | `get_measure_across_areas` | `places` | `county` | 84.2 | PASS |
| Q17 | No | `get_measure_across_areas` | `acs_profile` | `tract` | 95.0 | PASS |
| Q18 | No | `get_measure_across_areas` | `places` | `tract` | 96.3 | PASS |
| Q19 | No | `get_measure_across_areas` | `clh` | `tract` | 69.4 | PASS |
| Q20 | No | `get_measure_across_areas` | `acs_profile` | `cd` | 54.7 | PASS |
| Q21 | No | `get_measure_across_areas` | `acs` | `state` | 53.7 | PASS |
| Q22 | No | `get_measure_across_areas` | `usda_fea` | `county` | 55.7 | PASS |
| Q23 | No | `get_area_values` | `places`, `acs`, `acs_profile`, `clh` | `tract` | 55.3 | PASS |
| Q24 | No | `search_measures` | `places`, `acs`, `acs_profile`, `brfss`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea` | `state`, `county`, `tract`, `cd` | 51.7 | PASS |
| Q25 | No | `search_measures` | `places`, `acs_profile` | `county` | 50.4 | PASS |
| Q26 | No | `get_measure_details` | `places`, `acs_profile`, `brfss` | `state`, `county`, `tract`, `cd` | 51.9 | PASS |
| Q27 | No | `get_measure_details` | `cms_gv`, `usda_fea`, `epa_aqi`, `clh` | `state`, `county` | 50.9 | PASS |
| Q28 | No | `list_data_sources` | `places`, `acs`, `acs_profile`, `brfss`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea`, `health_centers`, `nursing_homes`, `tri_facilities` | `state`, `county`, `tract`, `cd` | 67.8 | PASS |
| Q29 | No | `find_places`, `find_places`, `find_places`, `find_places` | `places`, `acs_profile` | `state`, `county`, `cd` | 189.0 | PASS |
| Q30 | No | `find_places` | `places` | `county` | 47.9 | PASS |
| Q31 | No | `get_area_values` | `places`, `acs`, `acs_profile`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea` | `county` | 23.2 | PASS |
| Q32 | No | `get_area_values` | `acs`, `acs_profile`, `brfss`, `cms_gv` | `state` | 20.6 | PASS |
| Q33 | Yes (`ahrf_excluded`) | `search_measures`, `get_area_values` | `ahrf` | `county` | 109.6 | PASS |
| Q34 | Yes (`time_trend_one_period`) | `get_area_values`, `list_data_sources` | `places` | `county` | 97.6 | PASS |
| Q35 | Yes (`no_composite_score`) | `search_measures`, `get_measure_across_areas` | `places` | `county` | 108.4 | PASS |
| Q36 | Yes (`epa_aqi_no_monitor`) | `get_area_values`, `get_measure_across_areas` | `epa_aqi` | `county` | 107.5 | PASS |
| Q37 | Yes (`kentucky_brfss_not_published`) | `get_area_values`, `get_measure_across_areas` | `brfss` | `state` | 108.7 | PASS |
| Q38 | Yes (`cms_not_published_for_cd`) | `get_measure_across_areas`, `get_area_values` | `cms_gv`, `acs_profile` | `cd` | 105.8 | PASS |
| Q39 | Yes (`tracts_require_county`) | `get_measure_across_areas`, `get_measure_across_areas` | `places` | `tract` | 85.6 | PASS |
| Q40 | Yes (`medicare_original_beneficiaries`) | `get_area_values` | `cms_gv` | `county` | 54.2 | PASS |
| Q41 | Yes (`ct_pr_coverage_status`) | `get_area_values` | `usda_fea`, `cms_gv` | `county` | 54.3 | PASS |
| Q42 | Yes (`limits_and_truncation`) | `get_area_values`, `get_measure_across_areas` | `acs`, `places` | `county`, `tract` | 195.0 | PASS |
| Q43 | Yes (`ahrf_withheld_topic`) | `search_measures`, `get_area_values` | `ahrf` | `county` | 102.2 | PASS |
| Q44 | Yes (`ahrf_withheld_queries`) | `search_measures`, `search_measures`, `search_measures`, `search_measures` | `ahrf` | `county` | 195.7 | PASS |

## Failures

None — all checks passed.
