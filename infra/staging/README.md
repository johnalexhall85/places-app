# CHIP staging environment

Staging is a second copy of the stack on the same VM, used by the funder beta. The live demo is not affected by anything here.

| Part | Live | Staging |
|---|---|---|
| Checkout | `/home/john/places-app` (`main`) | `/home/john/chip-beta` (`beta`) |
| Database | `places` | `places_staging` (same PostGIS container) |
| Backend | `places-backend`, `127.0.0.1:8000` | `places-backend-staging`, `127.0.0.1:8001` |
| Webroot | `/var/www/places` | `/var/www/places-staging` |
| Nginx | port 80 | port 8080, closed in UFW |

Agent development backends use ports 8002 (Codex) and 8003 (Claude) against `places_staging`.

## Viewing staging

Port 8080 is not open to the internet. From your own computer:

```bash
ssh -L 8080:127.0.0.1:8080 john@<server>
```

Then open `http://localhost:8080/`. Staging has its own demo-access secrets and codes, stored only in `/home/john/chip-beta/backend/.env` and the staging database.

## Database selection

Every worktree's `backend/.env` must set `DATABASE_URL` to the `places_staging` database. The application, the area CLIs, and (since the beta) Alembic all follow it. The live service environment sets no `DATABASE_URL` and keeps using `places`. Legacy importers outside `app/area_pilot` are not part of the beta and must not be run from a worktree.

## Settings that differ from live

- The deploy script builds the frontend with `VITE_API_BASE_URL=/api` (the file `frontend/.env.production` that does this on live is git-ignored).
- `backend/.env` in `/home/john/chip-beta` sets `PROFILE_FRONTEND_BASE_URL=http://127.0.0.1:8080` so the PDF renderer loads profile pages from the staging site. At promotion, live needs its own value (`http://127.0.0.1`).
- A staging-only access code for browser checks is stored outside the repository at `/home/john/.local/share/chip/staging-beta-access-code` (mode 600, created by Codex).

## Deploying

```bash
infra/staging/deploy-staging.sh            # deploy beta as it is
infra/staging/deploy-staging.sh <branch>   # merge <branch> into beta, then deploy
```

The script takes a lock, refuses to run unless `DATABASE_URL` ends in `/places_staging`, aborts a conflicting merge, requires a single Alembic head, migrates, builds, syncs the webroot, restarts the staging service, and checks health, an anonymous 401, and the page. `gh` is not signed in on this VM, so merges into `beta` are local merges through this script, not GitHub pull requests.

## Refreshing the staging database

The first copy was `pg_dump -Fc places | pg_restore -d places_staging` on 2026-11-14 (about 70 GB). To refresh, stop `places-backend-staging`, drop and recreate `places_staging`, and repeat. Releases published only on staging are lost by a refresh.

## One-time installation

```bash
sudo cp infra/staging/places-backend-staging.service /etc/systemd/system/
sudo cp infra/staging/places-staging.nginx.conf /etc/nginx/sites-available/places-staging
sudo ln -s /etc/nginx/sites-available/places-staging /etc/nginx/sites-enabled/places-staging
sudo mkdir -p /var/www/places-staging
sudo systemctl daemon-reload && sudo systemctl enable places-backend-staging
sudo nginx -t && sudo systemctl reload nginx
```
