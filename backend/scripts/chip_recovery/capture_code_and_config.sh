#!/usr/bin/env bash
set -euo pipefail
umask 077
set_dir=${1:?provide new recovery-set directory}
repo=/home/john/places-app
install -d -m 700 "$set_dir" "$set_dir/deployment" "$set_dir/registries"
git -C "$repo" status --porcelain=v1 -uall > "$set_dir/git_worktree_status.txt"
git -C "$repo" ls-files > "$set_dir/git_tracked_files.txt"
git -C "$repo" rev-parse HEAD > "$set_dir/local_head.txt"
git -C "$repo" branch --show-current > "$set_dir/local_branch.txt"
GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=10' git -C "$repo" ls-remote --heads origin claude/improvements main > "$set_dir/remote_heads_at_backup.txt"
git -C "$repo" bundle create "$set_dir/local_git_history.bundle" HEAD
tar -C "$repo" --exclude='./.git' --exclude='./data' --exclude='./backend/.venv' --exclude='./frontend/node_modules' --exclude='./frontend/dist' --exclude='./backend/tmp' --exclude='./backend/cache' --exclude='./backend/app/data/profiles' --exclude='./backend/data/reports' --exclude='./frontend/public/reports' --exclude='./backend/alembic.ini' --exclude='./infra/docker-compose.yml' --exclude='.env*' --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pem' --exclude='*.key' -cf - . | zstd -T0 -3 -q -o "$set_dir/working_tree_no_env.new.tar.zst"
mv "$set_dir/working_tree_no_env.new.tar.zst" "$set_dir/working_tree_no_env.tar.zst"
for name in places_county_2025.json places_tract_2025.json acs_2024_b19013.json; do
  install -m 600 "$repo/backend/app/area_pilot/registry/$name" "$set_dir/registries/$name"
done
(cd "$set_dir" && sha256sum registries/*.json > registry_sha256.txt)
install -m 600 /etc/systemd/system/places-backend.service "$set_dir/deployment/places-backend.service"
install -m 600 /etc/systemd/system/chip-area-refresh.service "$set_dir/deployment/chip-area-refresh.service"
install -m 600 /etc/systemd/system/chip-area-refresh.timer "$set_dir/deployment/chip-area-refresh.timer"
install -m 600 /etc/nginx/sites-available/places-demo "$set_dir/deployment/places-demo.nginx.conf"
tar -C /var/www/places -cf - . | zstd -T0 -3 -q -o "$set_dir/deployed_webroot.new.tar.zst"
mv "$set_dir/deployed_webroot.new.tar.zst" "$set_dir/deployed_webroot.tar.zst"
python3 - "$repo" "$set_dir/deployment" <<'PY'
import re
import sys
from pathlib import Path
repo, out = (Path(x) for x in sys.argv[1:])
alembic, count = re.subn(r'(?m)^sqlalchemy\.url\s*=.*$', 'sqlalchemy.url = postgresql+psycopg://ROLE:SECURE_PASSWORD@HOST:5432/DATABASE', (repo/'backend/alembic.ini').read_text())
assert count == 1
(out/'alembic.recovery.template.ini').write_text(alembic)
compose, count = re.subn(r'(?m)^(\s*POSTGRES_PASSWORD:\s*).*$', r'\1${POSTGRES_PASSWORD_FROM_SECURE_STORE}', (repo/'infra/docker-compose.yml').read_text())
assert count == 1
(out/'docker-compose.recovery.template.yml').write_text(compose)
for path in (out/'alembic.recovery.template.ini', out/'docker-compose.recovery.template.yml'):
    path.chmod(0o600)
PY
