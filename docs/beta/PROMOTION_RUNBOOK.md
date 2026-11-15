# Promotion runbook: staging beta to the live demo

**Draft, 2026-11-15.** Nothing in this document has been run. It is executed only after John approves Gate 3, by one agent, in order. Stop at the first step that does not produce the stated result, and use the rollback section.

Live is `/home/john/places-app` (`main`), database `places`, service `places-backend` on 8000, webroot `/var/www/places`, Nginx port 80. Staging is described in [infra/staging/README.md](../../infra/staging/README.md).

## What promotion changes on live

| Item | From | To |
|---|---|---|
| Code | `main` at `0195959` | `main` fast-forwarded to the approved `beta` commit |
| Database schema | Alembic `c8f1e4a7d3b6` | `d5a2f7c9e1b4` (additive: three new tables) |
| PLACES release | two measures, `f735c524-…` | 13 measures, new county and tract releases created on live |
| ACS community product | not present | new release created on live; 437 district shapes loaded |
| Other nine pointers | unchanged | unchanged (verified before and after) |
| Webroot | pre-beta bundle | build of the approved commit |
| Backend environment | no `PROFILE_FRONTEND_BASE_URL` (check current value) | `PROFILE_FRONTEND_BASE_URL=http://127.0.0.1` so PDFs render from the live site |

Data is **re-ingested on live**, not copied from staging. Each live candidate must produce the same content digests that were reviewed on staging. If CDC or the Census Bureau has changed a file since staging, the digest differs: stop, and review that candidate as a new release.

Reviewed staging digests:

| Candidate | Semantic | Schema | Metadata | Measure set |
|---|---|---|---|---|
| PLACES county | `5cdc0b6404ec5fb5ef269694b3571d704e4259d94f9447703ec516ba149edea5` | `728eda33c40df4ba3dbbea46d69499d6848181ae1bdae160ed431a93d2d764dc` | `ae469fd6a9c93ef741bfef47f06d71ef704ee9a747ec67a1d3bdcad7f262fb28` | `4184fbed394ea3981097f48e532d2c218f09613ecd3c4f3d5c8242a5167354a4` |
| PLACES tract | `2eebfa924bc5b9e6730394d57c69460b7d8a8a21e2d02df3b6c718d0ae16ca34` | `93a997e5427db4d348cf979b382bfdf192f97b2f06b441be17558d7c1c75af34` | `c329052927df9db67b3751485df799df76ef59da2973919e86d8ee13f9fc02ac` | same |
| ACS community | `227317d9ceea9365a82781da0b8eac8a957177b3456c46a129dfb990c7953443` | `b0c8a7f77257d684030da13f911f10291fc6dd073febcf44468fa825005c56e0` | `897472a52b8dc52f80f63f455038fe2ca5552a93021eda44f6a575987d1fe41c` | not applicable |

## 0. Preconditions

- John's Gate 3 approval names the `beta` commit to promote.
- On staging at that commit: the full walkthrough passes, backend area and community tests pass, frontend tests and build pass.
- `git status` is clean in `/home/john/places-app`, and `main` is an ancestor of the approved commit.
- At least 100 GB free on `/`.
- No agent is running a staging deploy or an ingest.

## 1. Recovery set (before any change)

Create a fresh, dated recovery set of live following [chip_current_recovery_set.md](../../backend/docs/chip_current_recovery_set.md), into a new directory under `/home/john/chip-recovery/`. It must cover all ten current releases (the handbook's outstanding priority 1). Verify `SHA256SUMS`. Record the directory, dump size, and duration in the diary. The isolated restore test is recommended; if it is skipped, say so.

Also keep the application rollback pair:

```bash
install -d /home/john/places-app/data/deploy-recovery/beta-promotion-<date>
sudo rsync -a /var/www/places/ /home/john/places-app/data/deploy-recovery/beta-promotion-<date>/webroot-before/
git -C /home/john/places-app rev-parse HEAD > /home/john/places-app/data/deploy-recovery/beta-promotion-<date>/commit-before.txt
docker exec places_db psql -U places -d places -Atc \
  "select a.dataset_id,a.release_id from area_pilot.active_release a order by 1" \
  > /home/john/places-app/data/deploy-recovery/beta-promotion-<date>/pointers-before.txt
```

## 2. Code

```bash
cd /home/john/places-app
git merge --ff-only <approved beta commit>
cd backend && .venv/bin/pip install -r requirements.txt     # only if requirements.txt changed
```

The running backend keeps the old code in memory until it is restarted in step 5. The live `backend/.env` sets no `DATABASE_URL`, so every command below acts on `places`. Confirm that first: `grep -c '^DATABASE_URL' backend/.env` must print `0`.

## 3. Schema

```bash
cd /home/john/places-app/backend
.venv/bin/alembic current        # expect c8f1e4a7d3b6
.venv/bin/alembic upgrade head   # expect d5a2f7c9e1b4
```

The migration only creates tables. The old backend process is unaffected.

## 4. Data, in this order

For each candidate: `fetch-stage-validate`, then `review`, compare the printed digests with the table above, then `approve-publish` with those digests.

1. **PLACES county:** `python -m app.area_pilot.cli fetch-stage-validate`, `review`, `approve-publish … --measure-set-sha256 …`.
2. **PLACES tract:** `python -m app.area_pilot.cli fetch-stage-validate --geography tract`, `review`, `approve-publish … --measure-set-sha256 …`.
   Between 1 and 2 the active PLACES release is county-only: tract maps and tract tables for PLACES show nothing. On staging this window was about 20 minutes. Do both steps without a break.
3. **District boundaries:** `python -m app.area_pilot.acs_profile_cli load-cd-boundaries` (expect 52 files, 437 shapes).
4. **ACS community:** `python -m app.area_pilot.acs_profile_cli fetch-stage-validate`, `review`, `approve-publish`.

Then confirm that the nine untouched pointers equal `pointers-before.txt`, PLACES points at the new tract release, and the ACS community product has a pointer (eleven in total).

Note for the weekly timer: `chip-area-refresh.timer` runs PLACES and ACS income content checks on Sunday 03:00 UTC from this checkout. With the wider registry it will compare against the new PLACES release. Do not promote within a few hours of that run.

## 5. Application

```bash
cd /home/john/places-app/frontend
npm ci                      # if package-lock.json changed
npm run build               # frontend/.env.production supplies VITE_API_BASE_URL=/api on live; confirm the file exists
sudo rsync -a --delete dist/ /var/www/places/
# add PROFILE_FRONTEND_BASE_URL=http://127.0.0.1 to backend/.env if not present
sudo systemctl restart places-backend
curl -fsS http://127.0.0.1:8000/health
```

No Nginx change is needed: the community API is reached through the existing `/api/` block.

## 6. Verification on live

- Anonymous `GET /api/area/catalog` and `GET /api/community/catalog` through Nginx return 401; `/` returns 200.
- With an authorized session: the walkthrough (landing, search, the three showcase profiles, comparison, PDF, a topic, the district briefing) passes against the live address.
- `/explore/map`, every `/area/*` page, the three overlays, and the funding pages load.
- Ten values per showcase county match staging.
- Record commit, pointers, digests, and results in the diary; update the handbook's live state.

## Rollback

| Problem | Action |
|---|---|
| A candidate's digest differs from staging | Do not publish it. Live keeps its current release. Review the difference as a new release decision. |
| PLACES tract cannot be published after the county release went live | `python -m app.area_pilot.cli rollback f735c524-3fd4-4848-bfe3-1049cbc514dd` restores the previous combined release. |
| ACS community release is wrong | `python -m app.area_pilot.acs_profile_cli deactivate` hides the product; profiles then show those measures as not in release. |
| Application fault after restart | `git -C /home/john/places-app checkout <commit-before>` is **not** enough on its own: restore the matching webroot from `webroot-before/`, check out the previous commit, restart `places-backend`. The new tables and releases can stay; the old code ignores them. If PLACES stays on the 13-measure release, the old code's registry lists two measures and serves those two correctly. |
| Schema | Do not downgrade. The three added tables are inert for the old code. |

Data rollback and application rollback are independent. Never delete archives under `data/ingest`.

## Open items before this runbook is final

- Confirm the live value needed for `PROFILE_FRONTEND_BASE_URL` and whether `frontend/.env.production` exists in the live checkout (it is git-ignored).
- Add the final walkthrough command once Codex's X6 script includes the district leg.
- Decide whether to run the isolated restore test for the recovery set.
- AHRF redistribution terms remain unsettled; the product stays behind the access code.
