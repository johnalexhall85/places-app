# Historical periods: promotion runbook (Gate B)

Run only after John approves a specific `beta` commit. Every step is on the live stack (`/home/john/places-app`, database `places`, `places-backend`, `chip-mcp`, `/var/www/places`). Stop at the first failure and use the rollback steps.

## 0. Preconditions

- John has tried the year dropdown and the AI connector on staging and approved commit `<beta sha>`.
- On staging, every history release named in [status/claude.md](status/claude.md) is published, the walkthrough passes, and the MCP evaluation passes through `chip-mcp-staging`.
- `git -C /home/john/places-app status` is clean, and `main` is an ancestor of `<beta sha>`.

## 1. Recovery set

1. `mkdir -p data/deploy-recovery/history-<date>/`, then write into it:
   - `commit-before.txt` (`git rev-parse HEAD`)
   - `webroot-before/` (copy of `/var/www/places`)
   - `pointers-before.txt` (the `active_release` table), and `profiles-before.json` (`lookup.area_values` for `37145`, `54039`, `06019`, `5401`, and state `37`)
   - `alembic-before.txt`
2. Take a `pg_dump -Fc` of the `area_pilot` schema into the private recovery location used by earlier promotions, then verify it with `pg_restore --list`.

## 2. Code and schema

1. `git -C /home/john/places-app merge --ff-only <beta sha>`.
2. Run `cd backend && .venv/bin/alembic upgrade head`. The two migrations, `f7d1a4c8e2b6` and `a8c2e6f0d4b1`, are additive. Then `alembic current` must report `a8c2e6f0d4b1`.

## 3. Evidence archive and boundaries

1. Copy the staging-run archives from `/home/john/chip-claude/data/ingest/` into `/home/john/places-app/data/ingest/`, keeping their relative paths:
   - `history/` (boundaries, AHRF and CLH sources, per-run downloads)
   - the CMS, USDA, and AHRF current-file copies (already present on live)
   - `acs5_2024_b19013/boundaries/tl_2024_us_state.zip` (already present)

   Check every registry `sha256` pin with `sha256sum`.
2. From `backend/` on live, run `.venv/bin/python -m app.area_pilot.history.boundaries --vintage 2020 --vintage 2019`. It loads the TIGER archives already on disk. Area counts must equal staging: county 2020 3,221; tract 2020 85,395; tract 2019 74,001.

## 4. History releases (per product)

For each product in the order `cms_gv`, `usda_fea`, `brfss`, `epa_aqi`, `ahrf`, `acs`, `acs_profile`, `places`, `clh`:

1. Run `python -m app.area_pilot.history.cli --product <p> fetch-stage-validate`.
2. The new candidate's `semantic_sha256`, `schema_sha256`, `metadata_sha256`, and `observation_count` must **equal** the published staging release recorded in `status/claude.md`.
   - Archived-file products (CMS, USDA, AHRF, CLH, the EPA TIGER lookups) must match exactly.
   - Products fetched again from an API (BRFSS, EPA annual files, ACS, PLACES) can differ only if the publisher revised the source. In that case, stop, review the difference, and ask John.
3. Run `review`, then `approve-publish` with the staging digests.

After all products are done, the only pointer changes against `pointers-before.txt` must be the nine added `:history` rows.

## 5. Application

1. Build the frontend (`npm run build` with `VITE_API_BASE_URL=/api`), then `rsync --delete` it to `/var/www/places`. The bundle name must equal staging's.
2. Run `sudo systemctl restart places-backend chip-mcp`.

## 6. Verification

1. Check that `/api/health`, `/`, `/area/cms-gv`, and MCP `/healthz` return 200, and that the anonymous catalog returns 401.
2. Run the MCP evaluation through `https://mcp.publicdataobservatory.org/mcp` with expected values computed from live. It must pass completely.
3. Run the profile check: `lookup.area_values` for `37145`, `54039`, `06019`, `5401`, and state `37` must be identical to the pre-promotion capture taken in step 1. Profiles must not change.
4. John checks the signed-in maps on live.

## Rollback

- **Data:** run `python -m app.area_pilot.history.cli --product <p> deactivate` for each product. This removes only that product's `:history` pointer; current pointers and profiles are untouched.
- **Application:** run `git reset --hard $(cat commit-before.txt)` in the live checkout, restore `webroot-before/`, and restart both services. The history tables can stay; they are additive and unread without the pointers.
