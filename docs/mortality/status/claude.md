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
