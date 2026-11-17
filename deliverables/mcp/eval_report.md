# CHIP MCP Server Evaluation Report

- **Timestamp:** `2026-11-17T15:09:48.497402+00:00`
- **Commit:** `4a4408f`
- **Mode:** `live-mcp`
- **Server URL:** `http://127.0.0.1:8011/mcp`
- **Questions Passed:** **40 / 42**
- **Total Tool Calls:** `59`
- **Latency p50:** `50.9 ms`
- **Latency p95:** `126.2 ms`

## Summary Table

| ID | Trap | Tools | Products | Levels | Latency (ms) | Result |
|---|---|---|---|---|---:|---|
| Q01 | No | `find_places`, `get_area_values` | `places` | `county` | 134.3 | PASS |
| Q02 | No | `find_places`, `find_places`, `get_area_values` | `places`, `acs_profile` | `county` | 155.3 | PASS |
| Q03 | No | `get_area_values` | `acs`, `clh` | `county` | 55.0 | PASS |
| Q04 | No | `get_area_values` | `usda_fea`, `clh` | `county` | 14.7 | PASS |
| Q05 | No | `get_area_values` | `epa_aqi` | `county` | 54.4 | PASS |
| Q06 | No | `find_places`, `get_area_values` | `brfss` | `state` | 100.9 | PASS |
| Q07 | No | `find_places`, `get_area_values` | `acs_profile` | `cd` | 99.1 | PASS |
| Q08 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 57.8 | PASS |
| Q09 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 47.4 | PASS |
| Q10 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `county` | 207.9 | PASS |
| Q11 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `cd` | 5.4 | PASS |
| Q12 | No | `get_area_context` | `health_centers`, `nursing_homes`, `tri_facilities` | `state` | 130.5 | PASS |
| Q13 | No | `get_area_context`, `get_area_values` | `acs_profile` | `tract` | 97.9 | PASS |
| Q14 | No | `get_measure_across_areas` | `places` | `county` | 20.9 | PASS |
| Q15 | No | `get_measure_across_areas` | `places` | `county` | 58.1 | PASS |
| Q16 | No | `get_measure_across_areas` | `places` | `county` | 65.9 | **FAIL** |
| Q17 | No | `get_measure_across_areas` | `acs_profile` | `tract` | 125.7 | PASS |
| Q18 | No | `get_measure_across_areas` | `places` | `tract` | 87.1 | PASS |
| Q19 | No | `get_measure_across_areas` | `clh` | `tract` | 71.5 | PASS |
| Q20 | No | `get_measure_across_areas` | `acs_profile` | `cd` | 54.2 | PASS |
| Q21 | No | `get_measure_across_areas` | `acs` | `state` | 14.5 | PASS |
| Q22 | No | `get_measure_across_areas` | `usda_fea` | `county` | 16.0 | PASS |
| Q23 | No | `get_area_values` | `places`, `acs`, `acs_profile`, `clh` | `tract` | 55.9 | PASS |
| Q24 | No | `search_measures` | `places`, `acs`, `acs_profile`, `brfss`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea` | `state`, `county`, `tract`, `cd` | 52.6 | PASS |
| Q25 | No | `search_measures` | `places`, `acs_profile` | `county` | 51.5 | PASS |
| Q26 | No | `get_measure_details` | `places`, `acs_profile`, `brfss` | `state`, `county`, `tract`, `cd` | 52.3 | PASS |
| Q27 | No | `get_measure_details` | `cms_gv`, `usda_fea`, `epa_aqi`, `clh` | `state`, `county` | 50.7 | PASS |
| Q28 | No | `list_data_sources` | `places`, `acs`, `acs_profile`, `brfss`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea`, `health_centers`, `nursing_homes`, `tri_facilities` | `state`, `county`, `tract`, `cd` | 44.6 | PASS |
| Q29 | No | `find_places`, `find_places`, `find_places`, `find_places` | `places`, `acs_profile` | `state`, `county`, `cd` | 181.1 | PASS |
| Q30 | No | `find_places` | `places` | `county` | 48.8 | PASS |
| Q31 | No | `get_area_values` | `places`, `acs`, `acs_profile`, `clh`, `cms_gv`, `epa_aqi`, `usda_fea` | `county` | 23.0 | PASS |
| Q32 | No | `get_area_values` | `acs`, `acs_profile`, `brfss`, `cms_gv` | `state` | 39.9 | PASS |
| Q33 | Yes (`ahrf_excluded`) | `search_measures`, `get_area_values` | `ahrf` | `county` | 102.2 | PASS |
| Q34 | Yes (`time_trend_one_period`) | `get_area_values`, `list_data_sources` | `places` | `county` | 97.2 | PASS |
| Q35 | Yes (`no_composite_score`) | `search_measures`, `get_measure_across_areas` | `places` | `county` | 108.9 | PASS |
| Q36 | Yes (`epa_aqi_no_monitor`) | `get_area_values`, `get_measure_across_areas` | `epa_aqi` | `county` | 68.4 | PASS |
| Q37 | Yes (`kentucky_brfss_not_published`) | `get_area_values`, `get_measure_across_areas` | `brfss` | `state` | 69.1 | PASS |
| Q38 | Yes (`cms_not_published_for_cd`) | `get_measure_across_areas`, `get_area_values` | `cms_gv`, `acs_profile` | `cd` | 105.2 | PASS |
| Q39 | Yes (`tracts_require_county`) | `get_measure_across_areas`, `get_measure_across_areas` | `places` | `tract` | 86.5 | PASS |
| Q40 | Yes (`medicare_original_beneficiaries`) | `get_area_values` | `cms_gv` | `county` | 54.9 | PASS |
| Q41 | Yes (`ct_pr_coverage_status`) | `get_area_values` | `usda_fea`, `cms_gv` | `county` | 54.1 | PASS |
| Q42 | Yes (`limits_and_truncation`) | `get_area_values`, `get_measure_across_areas` | `acs`, `places` | `county`, `tract` | 236.3 | **FAIL** |

## Failures

### Q16: Show diagnosed diabetes prevalence (places:diabetes_crudeprev) across all 254 counties in Texas, including any county with no row in the published release.
- Call 0 (get_measure_across_areas): Serialized response size 63876 bytes exceeds cap of 60000 bytes
- Call 0 (get_measure_across_areas): Serialized response size 63876 bytes exceeds cap of 60000 bytes

### Q42: What happens if I request all 41 county measures for 12 counties at once (492 rows, exceeding the 400-row cap), or request median household income across all 2,498 tracts of Los Angeles County (06037)?
- Call 1 (get_measure_across_areas): Serialized response size 63103 bytes exceeds cap of 60000 bytes
- Call 1 (get_measure_across_areas): Serialized response size 63103 bytes exceeds cap of 60000 bytes

