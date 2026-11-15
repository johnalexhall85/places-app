#!/usr/bin/env bash
# Merge an agent branch into `beta` (optional) and deploy `beta` to the staging stack.
#
#   infra/staging/deploy-staging.sh                 # deploy the current beta checkout
#   infra/staging/deploy-staging.sh <branch>        # merge <branch> into beta, then deploy
#
# Staging only: database places_staging, service places-backend-staging (127.0.0.1:8001),
# webroot /var/www/places-staging, Nginx port 8080. It never touches the live stack.
set -euo pipefail

BETA_DIR=/home/john/chip-beta
WEBROOT=/var/www/places-staging
SERVICE=places-backend-staging
LOCK=/tmp/chip-staging-deploy.lock
BRANCH="${1:-}"

exec 9>"$LOCK"
if ! flock -w 900 9; then
  echo "Another staging deploy has held the lock for 15 minutes; giving up." >&2
  exit 75
fi

cd "$BETA_DIR"
[ "$(git rev-parse --abbrev-ref HEAD)" = "beta" ] || { echo "$BETA_DIR is not on beta" >&2; exit 1; }
[ -z "$(git status --porcelain --untracked-files=no)" ] || { echo "$BETA_DIR has local changes" >&2; exit 1; }

# Refuse to run unless this checkout is configured for the staging database.
DB_URL="$(grep -E '^DATABASE_URL=' backend/.env | tail -1 | cut -d= -f2-)"
case "$DB_URL" in
  */places_staging) ;;
  *) echo "backend/.env DATABASE_URL does not point at places_staging; refusing." >&2; exit 1 ;;
esac

BEFORE="$(git rev-parse HEAD)"
if [ -n "$BRANCH" ]; then
  if ! git merge --no-edit "$BRANCH"; then
    git merge --abort || true
    echo "Merge of $BRANCH into beta has conflicts; beta left at $BEFORE." >&2
    exit 2
  fi
fi
AFTER="$(git rev-parse HEAD)"
changed() { [ "$BEFORE" = "$AFTER" ] && return 1; git diff --name-only "$BEFORE" "$AFTER" -- "$@" | grep -q .; }

cd "$BETA_DIR/backend"
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; .venv/bin/pip install -q -r requirements.txt
elif changed backend/requirements.txt; then .venv/bin/pip install -q -r requirements.txt; fi
HEADS="$(.venv/bin/alembic heads | wc -l)"
[ "$HEADS" = "1" ] || { echo "Expected one Alembic head, found $HEADS" >&2; exit 3; }
.venv/bin/alembic upgrade head

cd "$BETA_DIR/frontend"
if [ ! -d node_modules ] || changed frontend/package-lock.json; then npm ci --no-audit --no-fund; fi
# frontend/.env.production is git-ignored, so set the API base here: the bundle must call /api on its own origin.
VITE_API_BASE_URL=/api npm run build
grep -rq 'localhost:8000' dist/assets/*.js && echo 'Warning: bundle still references localhost:8000 (fallback only if VITE_API_BASE_URL was unset)' >&2 || true
sudo -n rsync -a --delete dist/ "$WEBROOT/"

sudo -n systemctl restart "$SERVICE"
for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8001/health >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:8001/health >/dev/null
CODE="$(curl -s -o /dev/null -w '%{http_code}' 'http://127.0.0.1:8080/api/area/catalog')"
[ "$CODE" = "401" ] || { echo "Anonymous staging catalog returned $CODE, expected 401" >&2; exit 4; }
PAGE="$(curl -s -o /dev/null -w '%{http_code}' 'http://127.0.0.1:8080/')"
[ "$PAGE" = "200" ] || { echo "Staging page returned $PAGE" >&2; exit 4; }
echo "Staging deployed: beta $AFTER (was $BEFORE)"
