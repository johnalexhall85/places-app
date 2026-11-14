# CHIP area pipeline: Phase 4 operations

## Scope and policy

The weekly job verifies **full observation content** for the existing PLACES county and tract views and ACS B19013 in sequence. It uses the pinned ingestion adapters to retrieve and archive source responses, validate coverage, and compare semantic digests with the active releases. An identical result records a successful content check and raw-file provenance without a new release candidate or observations. It never publishes. A separate `--mode metadata` remains available for lightweight manual checks. Both registries explicitly set `auto_publish: false`. No later PLACES or ACS release is registered as compatible. The ACS adapter probes the 2025 five-year endpoint and holds if it exists. The PLACES views are pinned by their Socrata IDs; this job cannot discover a newly named PLACES view. Operators must inspect CDC release notes or catalog changes separately.

An unchanged metadata check means the source was reachable and the pinned metadata matched; it does **not** prove row values were unchanged or advance full-content freshness. Full verification calculates semantic identity. It records a duplicate run without a new candidate when semantic content, schema, and keys match, even if raw metadata serialization changed. Raw files and checksums remain attached as provenance. Changed semantic content under the same source label creates or reuses a held candidate. Unexpected schema, definitions, geography, boundaries, periods, units, and newly discovered products require review and a registry/adapter update; current pinned validation refuses unsupported forms. No candidate auto-publishes. A failed or held check leaves both active pointers unchanged.

The `release-reviewed-hold` action accepts only a same-label semantic revision whose validation checks all passed. It requires an operator note and the exact three reviewed digests. It rechecks ACS archives and observations or PLACES tract source samples before marking the candidate ready. Publication still requires the existing checksum-bound `approve-publish` command and reruns its checks. This is an explicit two-step operator decision, not scheduled publication.

## Schedule and limits

`chip-area-refresh.timer` runs at **Sunday 03:00 UTC**, with up to 15 minutes of randomized delay and `Persistent=true` for a missed run. The service is a separate one-shot Python process, runs as `john`, and writes JSON events to the systemd journal. Its 30-minute timeout and 3 GiB memory limit cover the measured sequential workload with headroom. A global file lock prevents overlapping check commands. Each product uses the same file lock as its manual CLI; ingestion also uses the existing PostgreSQL advisory lock for candidate and pointer operations. A busy product records a failed check while the other product continues.

Before a full download and again before staging, the ingestion commands require at least 5 GiB free plus 1 GiB (PLACES county) or 2 GiB (PLACES tract/ACS). Set `AREA_INGEST_MIN_FREE_GIB` to raise that floor. The initial VM had about 300 GiB available and about 756 MiB under `data/ingest`; no storage cleanup is automatic. The `status` command reports archive and staging use, available space, configured limits, separate metadata/content freshness, and a 14-day full-content verification overdue threshold independent of observation years. A metadata check cannot make full-content health current. Identical weekly runs still grow the archive; retention remains dry-run only.

PLACES interrupted retrieval keeps raw files and checkpoints, but a subsequent attempt downloads data pages again. Source revision and keys alone cannot verify that cached values stayed unchanged. ACS already starts a new run directory. A killed process leaves a `running` source-check row, which the next product check marks `interrupted`. Keep the retained files for diagnosis.

## Commands

Run from `/home/john/places-app/backend`:

```bash
.venv/bin/python -m app.area_pilot.operations status
.venv/bin/python -m app.area_pilot.operations check --mode metadata
.venv/bin/python -m app.area_pilot.operations check --mode content
.venv/bin/python -m app.area_pilot.operations check --mode content --product places
.venv/bin/python -m app.area_pilot.operations retention-report
.venv/bin/python -m app.area_pilot.cli fetch-stage-validate --geography tract
.venv/bin/python -m app.area_pilot.acs_cli fetch-stage-validate
```

For a held same-label revision, run `review CANDIDATE_UUID` through the corresponding product CLI. Confirm the source and release meaning with the publisher. Then run:

```bash
.venv/bin/python -m app.area_pilot.operations release-reviewed-hold \
  --product acs --candidate-id CANDIDATE_UUID \
  --semantic-sha256 REVIEWED_SEMANTIC_SHA \
  --schema-sha256 REVIEWED_SCHEMA_SHA \
  --metadata-sha256 REVIEWED_METADATA_SHA \
  --operator-note 'Publisher revision reviewed against archived source'
```

Use `--product places` for PLACES. Then use the corresponding guide's `approve-publish` command with the same three digests. Do not release holds caused by failed validation or unknown release compatibility.

Timer and journal commands:

```bash
sudo systemctl status chip-area-refresh.timer
systemctl list-timers chip-area-refresh.timer --all
sudo journalctl -u chip-area-refresh.service -n 100 --no-pager
sudo systemctl disable --now chip-area-refresh.timer
```

The dry-run retention report lists files with no `source_file` reference and all published/candidate release dependencies. **It deletes nothing.** Unreferenced files can belong to an interrupted job, so the report does not authorize removal. Preserve active and retained published releases, original files, manifests, checksums, approval records, and database rows.

## Recovery paths

**Active pointer:** Use `app.area_pilot.cli rollback RETAINED_PLACES_UUID` or `app.area_pilot.acs_cli rollback RETAINED_ACS_UUID` from `backend/`. A first release can be hidden with the matching `deactivate` command. These touch only the named product pointer; verify both pointers with `operations status` afterward. A disabled timer does not change pointers.

**Application deployment:** The current frontend is `/var/www/places/`. The prior ACS Phase 3 frontend is `/home/john/places-app/data/deploy-recovery/acs-phase3-20261113/webroot/`; check that it contains `index.html` and `assets/` and inspect its contents before copying. An application rollback requires a matching known backend checkout or saved files as well as a frontend copy. Keep the existing webroot as a separate backup before changing it. Do not use a generic `rsync --delete` recipe: verify the exact source, destination, and recovery contents, then perform any destructive synchronization as a separately reviewed deployment action. Pointer rollback needs no deployment copy or migration downgrade.

**Database recovery:** The Phase 4B audit initially found only `/home/john/chip_local.dump`, a March 9, 2026 dump without `area_pilot`. That older file remains intact. A current local recovery set was created November 14, 2026 at `/home/john/chip-recovery/20261114T004848Z/` on the production VM root disk. It includes a full `places` database dump, ingest archives, registries, deployment configuration, and code snapshot. See [Current recovery set](chip_current_recovery_set.md) for checksums, exact recovery commands, and isolated restore results. Neither pointer rollback nor frontend deployment recovery substitutes for a database backup. An independent copy off this VM remains outstanding.

On November 14, 2026, `pg_restore --no-owner --no-acl --exit-on-error` successfully restored that older dump in **15 minutes 48 seconds** into a separate PostGIS 16 container and Docker volume with `--network none`, no published ports, and no application services. The restored database occupied 18 GB, had 22 public tables, the `cdc_funding` schema, 3,153 `dim_county` rows, PostGIS 3.4.3, and Alembic revision `d1f4c7b9e2a6`. It had **zero `area_pilot` schemas**. This verifies the old dump is readable and its legacy data can be loaded in isolation; it does not test recovery of the current database, archives, registries, or active pointers. The temporary container and volume were removed after verification; the original dump was retained.

The [current recovery set guide](chip_current_recovery_set.md) records a measured proposal for nightly complete sets and seven daily plus four weekly retained sets. No backup timer, deletion policy, external storage, or production restore has been enabled. Choose independent storage and secure credential recovery before treating the local set as disaster recovery. Never delete current source archives or migrate down merely to change the active release.

## Commissioning checks

The Phase 4B service and timer were installed and verified with `systemd-analyze verify` and `systemctl show`. The timer is enabled and active; its next scheduled activation was **Sunday, November 15, 2026 at 03:12:55 UTC** when checked. There is one weekly timer, and its service invokes `operations check --mode content`; it downloads observations for PLACES county, PLACES tract, then ACS sequentially. A manual `--mode metadata` checks pinned metadata without bulk observation downloads.

On November 14, 2026, supervised identical-content checks produced these measured records:

| Product | Benchmarked check finished (UTC) | Duration | Archived API responses | Archived response bytes | Archive growth | Peak process RSS |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| PLACES | 00:21:34.603648 | 175.29 s | 272 | 230,437,128 | 230,477,259 B | 1,719,881,728 B |
| ACS | 00:25:41.587473 | 64.15 s | 109 | 8,960,775 | 8,960,775 B | 301,367,296 B |

The 381 archived API responses exclude the ACS release-discovery probe, any retried HTTP attempts, and 54 existing ACS boundary files referenced as provenance. PLACES also referenced its existing Connecticut boundary file. These are archived response counts, not exact network-attempt counts. Sequential work took about four minutes; the observed peak was about 1.72 GiB. A normal identical weekly run added about 239.4 MB of raw archives, or roughly 12.5 GB over 52 weeks if sizes remain similar. The 3 GiB memory and 30-minute limits fit this supervised workload on the current 7.7 GiB VM, but weekly archive growth requires a real backup and retention decision.

PLACES generated no candidate. An initial ACS run hit a tuple/list geography comparison error and created a false held candidate; the corrected run verified identical content. That false candidate was marked `rejected` under a guarded audit transaction, with its archived evidence retained. No active pointer changed or release was published. Active pointers remained PLACES `f735c524-3fd4-4848-bfe3-1049cbc514dd` and ACS `c1baba8e-ad3d-409f-b390-d312dbf19686`. Retention reporting remains dry-run only; the 117 previously reported unreferenced files were not deleted.

The final sequential check against the updated code finished PLACES at **00:34:30.295324 UTC** and ACS at **00:35:30.659248 UTC** on November 14, both `checked` with reason `identical_semantic_content_verified`. Its wall time was 4:02, with the same 272 PLACES and 109 ACS archived API responses and the same 230,477,259-byte and 8,960,775-byte archive growth. The combined process peak was 1,719,697,408 bytes; this maximum carries from PLACES into the ACS status detail because both ran in one process. The standalone ACS benchmark above measured 301,367,296 bytes. Database inspection found two published PLACES releases and one published plus one rejected ACS release, with no new candidate or observation rows from identical checks. The latest retention dry run lists 121 unreferenced files totaling 9,399,153 bytes, including new checkpoint manifests; none was deleted.
