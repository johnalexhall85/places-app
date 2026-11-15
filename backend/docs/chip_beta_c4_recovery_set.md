# Beta C4 local recovery rehearsal

## Scope

This is a new, point-in-time copy of the **live pre-beta** CHIP stack, taken while live services stayed online. The set is `/home/john/chip-recovery/20261115T011923Z/`. It does not contain the staging-only C1–C3 releases and does not authorize promotion. At Gate 3, take another fresh live set immediately before any live code, schema, data, or webroot change, as required by the [promotion runbook](../../docs/beta/PROMOTION_RUNBOOK.md).

The set contains a consistent custom-format PostgreSQL dump, role definitions without passwords, the dump catalog, published-source manifest, raw ingest archive, source and installed-configuration snapshots without runtime `.env` contents, Git bundle, deployed webroot, checksums, and read-only validation baselines. The validation SQL was extended to count the currently active AHRF, CLH, EPA AQI, CMS GV, USDA FEA, HRSA site, TRI, and nursing-home rows in addition to PLACES, ACS income, spatial joins, migration state, and all release pointers.

The commands and temporary PostGIS 16 `template0` restore procedure are in [the original recovery-set guide](chip_current_recovery_set.md); substitute this set directory for the older `20261114T004848Z` directory. The new temporary test container and volume are named `chip-beta-c4-restore` and `chip_beta_c4_restore_test`. The test container has no network or published ports. Its database is never used by an application service.

## Verification record

| Check | Result |
|---|---|
| Dump and catalog | 11,605,083,277-byte custom dump; 20 minutes 29 seconds (01:19:23–01:39:52 UTC); 1,690 catalog entries |
| Live validation baseline | 66 read-only result lines, including ten active pointers and Alembic `c8f1e4a7d3b6` |
| Published-source manifest and archive checksum | 1,405 distinct published source files verified inside the 1,145,949,471-byte raw-ingest archive; 1,830 release-to-source references |
| Code, installed configuration, and webroot snapshot | Captured without runtime `.env` files |
| Manifest and `SHA256SUMS` | 31 entries passed before isolated restore; final rebuilt manifest records `restore_test: passed`, and all 37 final checksums passed |
| Isolated restore and byte-for-byte baseline comparison | `pg_restore --exit-on-error` completed in 42 minutes 40 seconds (01:41:34–02:24:20 UTC) with an empty error log; all 66 restored validation lines matched the live baseline byte for byte |
| Test container and volume cleanup | `chip-beta-c4-restore` and `chip_beta_c4_restore_test` removed; root filesystem had about 205 GiB free afterward |

The first final-manifest pass used `restore_test_*` filenames, while the versioned manifest helper expects `database_restore_*`, and wrote the checksum-check output inside the set, making that log self-referential when the manifest was rebuilt. The test database itself had restored and matched the baseline. The files were renamed to the helper's expected convention, the transient check log was removed, and the manifest and all final checksums were regenerated successfully. No restore retry or live database write was needed.

This set is on the same VM disk as the live database, so it is a local recovery rehearsal. An independently stored encrypted copy and a secure credential-recovery path remain outstanding; neither is represented by this set. No automatic backup schedule or retention deletion is enabled.
