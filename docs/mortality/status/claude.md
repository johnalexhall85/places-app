# Claude status: mortality

## M0 (2026-11-21T02:30Z)
- Wrote the plan, the contract, and the AGENTS.md section.
- Archived the sources under `data/ingest/` (hashes are in the contract).
- Migration `c3e7a1f5b9d2` was applied to `places_staging` and passed a downgrade/upgrade round trip. Live is not touched.
- Next: M1 is dispatched to Antigravity.

## M1 review and staging (2026-11-21T02:00Z)
- Reviewed Antigravity's M1 and committed it as `5df53b5`.
- Claude updated two tests that hard-code product sets (`test_area_lookup`, `test_mcp_integration`). Backend: 66 passed, 1 skipped. MCP: 28 passed. Snapshots unchanged.
- Staged from the archive (`--skip-fetch`) on `places_staging`: candidate `0563fdb4-c049-436c-995f-dff439c5aac2`.
  - 6,526 matched rows, 2 national rows, and 38 source-only rows (16 legacy Connecticut, 22 with no 2024 boundary: territories and 02261).
  - The 36 suppressed counties in the source are 12 published as `suppressed` and 24 source-only.
- Published on staging. Durham County (37063) reads 227.2 and 71.2, and the US reads 315.3 and 75.9, matching the source. Connecticut planning regions read `not_in_release`.
- Deployed staging: `beta` `fadf071`. `/area/heart-stroke-mortality` returns 200.
- M2 has been dispatched.

## M2 review and staging (2026-11-21T02:40Z)
- Committed Antigravity's M2 with Claude's changes:
  - Contract Amendment 1: NCI's state-file codes 02900, 11001, and 72001 map to AK, DC, and PR when the name matches.
  - The matching parser test.
  - Count and product-set test updates.
  - The charts test now excludes the mortality products, which `/deaths` serves.
- Backend: 78 passed, 1 skipped. MCP: 28 passed. Snapshots unchanged.
- Staging candidate `2353290d-4444-41e4-90ea-fb4343aa20dd`: 156 state, 3 national, and 9,396 county observations, 1,418 of them suppressed. Source-only rows: 24 legacy Connecticut, 3 Puerto Rico totals in the county files, 6 with no boundary, and 3 duplicate US rows.
- Published on staging. Durham all sites 132.6 (127.2–138.2), lung 25.1, and colorectal 11.8, matching the source.
- M3 has been dispatched.

## M3 review and staging (2026-11-21T03:10Z)
- Committed Antigravity's M3, after Claude updated the MCP count test to 13.
- Area and community: 315 passed, 1 skipped. MCP: 28 passed. Snapshots unchanged.
- Antigravity added a per-product `ci95` label hook (`UNCERTAINTY_LABEL`) in `lookup._row`, so drug poisoning reads "95% interval from NCHS's model". Other `ci95` products are unchanged.
- Staging candidate `09113340-499e-4ce0-a82c-1f36c05a6172`: 59,318 matched and 266 source-only stage rows (2003–2021), and 3,122 county observations for 2021, all available.
- Published on staging. Durham reads 23.87115 (22.12165–25.75957), matching the source.
- M6 has been dispatched.

## M6 review and staging deploy (2026-11-21T03:40Z)
- Committed Antigravity's M6. Deployed staging at `beta` `1d7ae37`.
- The signed-in walkthrough passed, after Claude corrected two counts that had been stale since SVI and NRI. The screenshots are good.
- Gate A passed (John: "This is great. Approved. Go live.").

## Gate B: live (2026-11-21T15:17Z)
- Migration `c3e7a1f5b9d2` applied on live; the three releases are published with the staging digests; bundle `index-D6uKhaMq.js` deployed. The package is complete.
