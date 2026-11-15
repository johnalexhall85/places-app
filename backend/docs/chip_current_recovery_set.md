# CHIP current local recovery set — 2026-11-14

**Current-state correction, 2026-11-15:** This document records the older `20261114T004848Z` set and retains its exact commands as an operator example. The newer pre-beta live set and its verification record are in [the beta C4 recovery guide](chip_beta_c4_recovery_set.md). Substitute a new dated directory before repeating any command; neither local set is an independent off-VM backup.

## Storage and scope

`/dev/vda` is the existing 500 GB system disk. Its ext4 partition `/dev/vda2` is mounted at `/`; there is no separate attached or unmounted data volume. PostgreSQL's `infra_places_db_data` Docker volume, `/home/john/places-app/data/ingest`, the deployed webroot, and this recovery set all reside on that root filesystem. The set is `/home/john/chip-recovery/20261114T004848Z/`, with a private directory and files. It is a **local recovery copy on the production VM**, not an independent copy of that VM or disk.

The set contains the full custom-format `places` database dump, its `pg_restore` catalog, password-free role definitions, current extensions and versions, the raw ingest archive, checksums for every published-source file, three CHIP registries, a working-tree source snapshot, a Git history bundle and status, installed systemd and Nginx configuration, redacted configuration templates, and the exact deployed webroot. `recovery_manifest.json` records hashes and timestamps. Runtime `.env` files, the Census API key file, and database/demo credentials require separate secure recovery. Treat the whole set as sensitive because existing Git history may contain embedded credentials; use encryption for any future independent transfer.

PostgreSQL is 16.4 with PostGIS 3.4.3 and migration head `a6c52d9e7b10`. Required extensions are `fuzzystrmatch`, `plpgsql`, `postgis`, `postgis_tiger_geocoder`, and `postgis_topology`. The `places` login role is required. The backend service runs from `/home/john/places-app/backend` on a dirty working tree based on Git commit `ad3a6677eda2868207ac6d24b59e1bef59034911`. That branch is three commits ahead of `origin/claude/improvements`; CHIP pipeline files and this operator documentation are untracked. The remote cannot reconstruct this deployment. No commit or push was made.

## Exact local backup commands

Use a new dated private directory for every repeat backup and leave prior sets intact; replace the commissioned `set_dir` below with that new path. Before repeating for a changed release, update the validation SQL to query that release and capture a new production baseline. The database dump uses PostgreSQL's consistent snapshot while services remain running. The helper scripts capture the source tree and installed configuration without copying runtime `.env` files.

```bash
set -euo pipefail
umask 077
set_dir=/home/john/chip-recovery/20261114T004848Z
install -d -m 700 "$set_dir"
date -u +%Y-%m-%dT%H:%M:%SZ > "$set_dir/database_dump_started_utc.txt"
/usr/bin/time -v -o "$set_dir/database_dump_time.txt" \
  docker exec places_db pg_dump -U places -d places --format=custom \
  --compress=6 --lock-wait-timeout=30s > "$set_dir/places_current.dump" \
  2> "$set_dir/database_dump_stderr.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$set_dir/database_dump_finished_utc.txt"
docker exec places_db pg_dumpall -U places --globals-only --no-role-passwords \
  > "$set_dir/globals_no_passwords.sql"
pg_restore -l "$set_dir/places_current.dump" > "$set_dir/database_toc.txt"
(cd "$set_dir" && sha256sum places_current.dump > database_sha256.txt)
install -m 600 /home/john/places-app/backend/scripts/chip_recovery/restore_validation.sql \
  "$set_dir/restore_validation.sql"
docker exec -i places_db psql -U places -d places -X -A -t -F '|' \
  -v ON_ERROR_STOP=1 -f - < "$set_dir/restore_validation.sql" \
  > "$set_dir/production_validation_baseline.txt"
(cd /home/john/places-app/backend && PYTHONPATH=. .venv/bin/python \
  scripts/chip_recovery/build_published_source_manifest.py \
  "$set_dir/published_source_manifest.json")
tar -C /home/john/places-app/data -cf - ingest | \
  zstd -T0 -3 -q -o "$set_dir/raw_ingest.tar.zst"
zstd -t -q "$set_dir/raw_ingest.tar.zst"
zstd -dc "$set_dir/raw_ingest.tar.zst" | \
  python3 /home/john/places-app/backend/scripts/chip_recovery/verify_raw_ingest.py \
  "$set_dir/published_source_manifest.json"
bash /home/john/places-app/backend/scripts/chip_recovery/capture_code_and_config.sh "$set_dir"
(cd /home/john/places-app/backend && PYTHONPATH=. .venv/bin/python \
  scripts/chip_recovery/build_recovery_manifest.py "$set_dir")
(cd "$set_dir" && sha256sum -c SHA256SUMS)
```

`published_source_manifest.json` comes from `area_pilot.source_file` joined to published releases. It stores paths, sizes, SHA-256 hashes, and release/run IDs, without source API keys. The verifier checks every referenced file *inside* the compressed archive. The working-tree snapshot excludes runtime environment files, virtual environments, data, and node modules; it includes untracked CHIP code and migration files. Installed service/Nginx files and the deployed webroot are copied separately.

## Exact isolated restore test

These commands create a temporary PostGIS 16 database with no network, published ports, or application services. The image initially creates `chip_restore` from a PostGIS template containing `tiger`; the commands recreate that **temporary** database from clean `template0` so the dump can restore its own extension schemas. The trust setting is confined to this isolated test container and must not be used for a networked production database.

```bash
set -euo pipefail
set_dir=/home/john/chip-recovery/20261114T004848Z
docker volume create chip_current_restore_test
docker run --rm -d --name chip-current-restore --network none \
  --memory 3g --cpus 2 \
  --mount type=volume,source=chip_current_restore_test,target=/var/lib/postgresql/data \
  --mount type=bind,source="$set_dir/places_current.dump",target=/restore/places_current.dump,readonly \
  -e POSTGRES_USER=places -e POSTGRES_DB=chip_restore \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgis/postgis:16-3.4
until docker exec chip-current-restore pg_isready -U places -d chip_restore; do sleep 2; done
docker exec chip-current-restore psql -U places -d postgres -v ON_ERROR_STOP=1 \
  -Atc "DROP DATABASE chip_restore WITH (FORCE)"
docker exec chip-current-restore psql -U places -d postgres -v ON_ERROR_STOP=1 \
  -Atc "CREATE DATABASE chip_restore TEMPLATE template0 OWNER places"
/usr/bin/time -v docker exec chip-current-restore pg_restore -U places \
  -d chip_restore --exit-on-error /restore/places_current.dump
docker exec -i chip-current-restore psql -U places -d chip_restore \
  -X -A -t -F '|' -v ON_ERROR_STOP=1 -f - \
  < "$set_dir/restore_validation.sql" > "$set_dir/restored_validation.txt"
cmp "$set_dir/production_validation_baseline.txt" "$set_dir/restored_validation.txt"
docker stop chip-current-restore
docker volume rm chip_current_restore_test
(cd /home/john/places-app/backend && PYTHONPATH=. .venv/bin/python \
  scripts/chip_recovery/build_recovery_manifest.py "$set_dir")
```

`restore_validation.sql` uses a read-only transaction to compare migration state, active pointers, published releases, boundaries, representative observations, and PLACES/ACS spatial map and table joins. It also checks PostGIS geometry simplification and serialization. No application service is pointed at the restored copy.

For a real recovery, provision PostgreSQL 16/PostGIS 3.4 with the listed extensions and a securely configured `places` role. Restore the dump into a **new** database, inspect the manifest and checksums, and stage the code, raw files, and webroot with these commands:

```bash
set -euo pipefail
set_dir=/home/john/chip-recovery/20261114T004848Z
(cd "$set_dir" && sha256sum -c SHA256SUMS)
createdb -U places --template=template0 chip_recovered
pg_restore -U places -d chip_recovered --exit-on-error "$set_dir/places_current.dump"
install -d -m 700 /home/john/chip-recovery-staging/source /home/john/chip-recovery-staging/data /home/john/chip-recovery-staging/webroot
tar -I zstd -xf "$set_dir/working_tree_no_env.tar.zst" -C /home/john/chip-recovery-staging/source
tar -I zstd -xf "$set_dir/raw_ingest.tar.zst" -C /home/john/chip-recovery-staging/data
tar -I zstd -xf "$set_dir/deployed_webroot.tar.zst" -C /home/john/chip-recovery-staging/webroot
```

Recover runtime credentials through the separate secure channel, run the validation SQL against the new database, and review target paths and service configuration before any production cutover. Do not replace the current database or start services against the isolated test copy.

## Commissioning and proposed schedule

The current dump is **11,558,675,568 bytes** and took **19 minutes 41 seconds**. The compressed full-ingest archive is **606,806,548 bytes**; all **1,311 distinct files** referenced by **1,732 published-source rows** passed source and archive checksum verification. The dump catalog has 1,578 entries, including `area_pilot` and `public.alembic_version`.

Proposed cadence: a complete database, source archive, registries, code, and deployment set nightly at **00:30 UTC**, plus a weekly complete set on **Sunday 04:30 UTC**, after the existing Sunday 03:00–03:15 content-check window and its 30-minute service limit. Use an exclusive backup lock, fail on low free space, verify each checksum and catalog, and alert on failure. Retain seven daily and four weekly complete sets. At current measured sizes, eleven copies of the database plus compressed ingest/code/webroot archives require about **about 125.43 GiB**, before growth or filesystem overhead. The schedule and deletion policy are **proposed only**; no timer or automatic retention removal is enabled. An independent encrypted copy outside the production VM and a tested way to recover runtime credentials remain outstanding.

The isolated restore finished at **01:52:06 UTC** in **41 minutes 38 seconds**, with an empty `pg_restore` error log. The first attempt exposed a PostGIS image template conflict (`tiger` already existed); recreating only the temporary test database from `template0` resolved it. The successful retry restored owners, ACLs, all schemas, and materialized views. Its 41-line read-only validation output matched the production baseline byte for byte. This includes migration `a6c52d9e7b10`, the PLACES and ACS active pointers, 884 CT tract boundaries, 3,222 county/52 state/85,396 tract ACS boundaries, 6,286 PLACES county and 167,044 PLACES tract observations, 3,222 county/52 state/85,382 tract ACS observations, representative values, four spatial map/table queries, and a valid PostGIS geometry result. Restored PostgreSQL 16.4 and PostGIS 3.4.3 match production. The test container and temporary volume were removed; no service was directed to the restored database. The root filesystem had **309,042,225,152 bytes free (about 287.8 GiB)** afterward. At current set sizes, adding ten more complete sets to reach seven daily plus four weekly would leave roughly **174 GiB** free, before database/archive growth and operational headroom.
