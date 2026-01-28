#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$ROOT_DIR/infra"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# ---- helpers ----
log() { echo -e "\n==> $*\n"; }

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found. Install Docker Desktop / Docker Engine first."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: docker compose not available. Use Docker Desktop or install compose plugin."
  exit 1
fi

# ---- start db ----
log "Starting database via docker compose in $INFRA_DIR"
cd "$INFRA_DIR"
docker compose up -d

log "Waiting for Postgres to be ready..."
# Prefer compose service health if defined; otherwise poll pg_isready inside container.
DB_CID="$(docker compose ps -q | head -n 1 || true)"

# Try to find a postgres container in this compose project
PG_CID="$(docker compose ps -q | xargs -r docker inspect --format '{{.Id}} {{.Config.Image}}' 2>/dev/null | awk '/postgres/ {print $1; exit}')"

if [ -z "${PG_CID:-}" ]; then
  # fallback: pick the first container
  PG_CID="$DB_CID"
fi

# Poll pg_isready inside the container (works for official postgres images)
READY=0
for i in {1..60}; do
  if docker exec "$PG_CID" pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done

if [ "$READY" -ne 1 ]; then
  echo "ERROR: Postgres did not become ready."
  echo "Try: cd infra && docker compose logs --tail=200"
  exit 1
fi

log "Postgres is ready."

# ---- start backend ----
log "Starting backend (FastAPI) on http://localhost:8000"
cd "$BACKEND_DIR"

if [ ! -d ".venv" ]; then
  echo "ERROR: backend/.venv not found. Create venv and install deps first."
  exit 1
fi

# shellcheck disable=SC1091
source ".venv/bin/activate"

# Run backend in background
( uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload ) &
BACK_PID=$!

# ---- start frontend ----
log "Starting frontend (Vite) on http://localhost:5173"
cd "$FRONTEND_DIR"

if [ ! -d "node_modules" ]; then
  log "node_modules missing; running npm install"
  npm install
fi

( npm run dev -- --host 0.0.0.0 --port 5173 ) &
FRONT_PID=$!

log "All services started."
echo "Backend:  http://localhost:8000 (docs: /docs)"
echo "Frontend: http://localhost:5173"
echo
echo "To stop:  Ctrl+C (or run ./dev-down.sh)"

# Keep script running; stop both on Ctrl+C
trap 'echo; echo "Stopping..."; kill $BACK_PID $FRONT_PID 2>/dev/null || true; exit 0' INT TERM
wait
