# CHIP MCP Server Evaluation Report

- **Timestamp:** `2026-11-17T21:06:46.850673+00:00`
- **Commit:** `8d715cf`
- **Mode:** `live-mcp`
- **Server URL:** `http://127.0.0.1:8011/mcp`
- **Questions Passed:** **54 / 54**
- **Total Tool Calls:** `75`
- **Latency p50:** `60.3 ms`
- **Latency p95:** `181.8 ms`

## Summary Table

| ID | Trap | Tools | Products | Levels | Latency (ms) | Result |
|---|---|---|---|---|---:|---|
| Q01 | No | `find_places`, `get_area_values` | `places` | `county` | 206.3 | PASS |
| Q02 | No | `find_places`, `find_places`, `get_area_values` | `places`, `acs_profile` | `county` | 178.3 | PASS |
| Q03 | No | `get_area_values` | `acs`, `clh` | `county` | 22.9 | PASS |
| Q04 | No | `get_area_values` | `usda_fea`, `clh` | `county` | 64.4 | PASS |
| Q05 | No | `get_area_values` | `epa_aqi` | `county` | 62.3 | PASS |
| Q06 | No | `find_places`, `get_area_values` | `brfss` | `state` | 112.7 | PASS |
| Q07 | No | `find_places`, `get_area_values` | `acs_profile` | `cd` | 111.9 | PASS |
| Q08 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 93.5 | PASS |
| Q09 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 66.8 | PASS |
| Q10 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 309.3 | PASS |
| Q11 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `cd` | 1230.4 | PASS |
| Q12 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `state` | 49.3 | PASS |
| Q13 | No | `get_area_context`, `get_area_values` | `acs_profile` | `tract` | 105.1 | PASS |
| Q14 | No | `get_measure_across_areas` | `places` | `county` | 70.6 | PASS |
| Q15 | No | `get_measure_across_areas` | `places` | `county` | 146.0 | PASS |
| Q16 | No | `get_measure_across_areas` | `places` | `county` | 48.3 | PASS |
| Q17 | No | `get_measure_across_areas` | `acs_profile` | `tract` | 189.8 | PASS |
| Q18 | No | `get_measure_across_areas` | `places` | `tract` | 147.6 | PASS |
| Q19 | No | `get_measure_across_areas` | `clh` | `tract` | 123.1 | PASS |
| Q20 | No | `get_measure_across_areas` | `acs_profile` | `cd` | 61.8 | PASS |
| Q21 | No | `get_measure_across_areas` | `acs` | `state` | 61.7 | PASS |
| Q22 | No | `get_measure_across_areas` | `usda_fea` | `county` | 64.7 | PASS |
| Q23 | No | `get_area_values` | `places`, `acs`, `acs_profile`, `clh` | `tract` | 61.3 | PASS |
| Q24 | No | `search_measures` | `places`, `acs`, `acs_profile`, `brfss`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea` | `state`, `county`, `tract`, `cd` | 19.0 | PASS |
| Q25 | No | `search_measures` | `places`, `acs_profile` | `county` | 25.9 | PASS |
| Q26 | No | `get_measure_details` | `places`, `acs_profile`, `brfss` | `state`, `county`, `tract`, `cd` | 64.7 | PASS |
| Q27 | No | `get_measure_details` | `cms_gv`, `usda_fea`, `epa_aqi`, `clh` | `state`, `county` | 64.8 | PASS |
| Q28 | No | `list_data_sources` | `places`, `acs`, `acs_profile`, `brfss`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea`, `health_centers`, `nursing_homes`, `tri_facilities` | `state`, `county`, `tract`, `cd` | 110.7 | PASS |
| Q29 | No | `find_places`, `find_places`, `find_places`, `find_places` | `places`, `acs_profile` | `state`, `county`, `cd` | 194.7 | PASS |
| Q30 | No | `find_places` | `places` | `county` | 53.7 | PASS |
| Q31 | No | `get_area_values` | `places`, `acs`, `acs_profile`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea` | `county` | 39.8 | PASS |
| Q32 | No | `get_area_values` | `acs`, `acs_profile`, `brfss`, `cms_gv` | `state` | 33.9 | PASS |
| Q33 | Yes (`ahrf_excluded`) | `search_measures`, `get_area_values` | `ahrf` | `county` | 74.2 | PASS |
| Q34 | No | `get_measure_over_time` | `cms_gv` | `county` | 79.8 | PASS |
| Q35 | Yes (`no_composite_score`) | `search_measures`, `get_measure_across_areas` | `places` | `county` | 85.6 | PASS |
| Q36 | Yes (`epa_aqi_no_monitor`) | `get_area_values`, `get_measure_across_areas` | `epa_aqi` | `county` | 124.7 | PASS |
| Q37 | Yes (`kentucky_brfss_not_published`) | `get_area_values`, `get_measure_across_areas` | `brfss` | `state` | 128.2 | PASS |
| Q38 | Yes (`cms_not_published_for_cd`) | `get_measure_across_areas`, `get_area_values` | `cms_gv`, `acs_profile` | `cd` | 119.0 | PASS |
| Q39 | Yes (`tracts_require_county`) | `get_measure_across_areas`, `get_measure_across_areas` | `places` | `tract` | 87.4 | PASS |
| Q40 | Yes (`medicare_original_beneficiaries`) | `get_area_values` | `cms_gv` | `county` | 62.5 | PASS |
| Q41 | Yes (`ct_pr_coverage_status`) | `get_area_values` | `usda_fea`, `cms_gv` | `county` | 60.4 | PASS |
| Q42 | Yes (`limits_and_truncation`) | `get_area_values`, `get_measure_across_areas` | `acs`, `places` | `county`, `tract` | 306.1 | PASS |
| Q43 | Yes (`ahrf_withheld_topic`) | `search_measures`, `get_area_values` | `ahrf` | `county` | 117.3 | PASS |
| Q44 | Yes (`ahrf_withheld_queries`) | `search_measures`, `search_measures`, `search_measures`, `search_measures` | `ahrf` | `county` | 59.3 | PASS |
| Q45 | No | `get_measure_across_areas` | `cms_gv` | `county` | 78.1 | PASS |
| Q46 | No | `get_area_values` | `cms_gv` | `county` | 66.1 | PASS |
| Q47 | No | `search_measures` | `places`, `brfss` | `state`, `county`, `tract` | 20.8 | PASS |
| Q48 | No | `get_measure_details` | `cms_gv` | `state`, `county` | 58.9 | PASS |
| Q49 | No | `get_measure_over_time` | `cms_gv` | `county` | 38.9 | PASS |
| Q50 | Yes (`cd_no_earlier_periods`) | `get_measure_across_areas` | `acs_profile` | `cd` | 57.3 | PASS |
| Q51 | Yes (`ahrf_over_time_withheld`) | `get_measure_over_time` | `ahrf` | `county` | 43.0 | PASS |
| Q52 | Yes (`unpublished_period_skipped`) | `get_area_values` | `brfss` | `state` | 60.4 | PASS |
| Q53 | Yes (`no_computed_change`) | `get_area_values`, `get_area_values` | `cms_gv` | `county` | 128.1 | PASS |
| Q54 | Yes (`across_areas_sort_single_period`) | `get_measure_across_areas` | `cms_gv` | `county` | 63.5 | PASS |

## Failures

None — all checks passed.
