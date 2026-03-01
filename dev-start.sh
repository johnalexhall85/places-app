#!/usr/bin/env bash
set -e

echo "🚀 Starting PLACES dev environment"
echo "---------------------------------"

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ---------- DATABASE ----------
echo "🗄️  Checking database (Docker)..."
if command -v docker >/dev/null 2>&1; then
  if docker ps | grep -q postgres; then
    echo "✅ Postgres container already running"
  else
    if [ -f "$ROOT_DIR/docker-compose.yml" ]; then
      echo "▶️  Starting Postgres via docker-compose"
      docker compose up -d
    else
      echo "⚠️  docker-compose.yml not found — assuming DB already running"
    fi
  fi
else
  echo "⚠️  Docker not found — assuming DB already running"
fi

# ---------- BACKEND ----------
echo
echo "🐍 Starting FastAPI backend"
cd "$ROOT_DIR/backend"

if [ ! -d ".venv" ]; then
  echo "❌ backend/.venv not found"
  echo "Run: python -m venv .venv && pip install -r requirements.txt"
  exit 1
fi

source .venv/bin/activate

echo "▶️  Applying database migrations (alembic upgrade head)"
alembic upgrade head

echo "▶️  Starting uvicorn (http://localhost:8000)"
uvicorn app.main:app --reload &
BACKEND_PID=$!

# ---------- FRONTEND ----------
echo
echo "🌐 Starting frontend (Vite + React)"

if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
  echo "📦 Installing frontend dependencies..."
  (cd "$ROOT_DIR/frontend" && npm install)
fi
if [ ! -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ]; then
  echo "📦 Reinstalling frontend dependencies (vite missing)..."
  (cd "$ROOT_DIR/frontend" && npm install)
fi

echo "▶️  Starting Vite (http://localhost:5173)"
(cd "$ROOT_DIR/frontend" && npm run dev) &
FRONTEND_PID=$!

# ---------- STATUS ----------
echo
echo "✅ All services started"
echo "---------------------------------"
echo "Backend:  http://localhost:8000/health"
echo "Frontend: http://localhost:5173"
echo
echo "Press Ctrl+C to stop everything"

# ---------- CLEANUP ----------
trap "echo; echo '🛑 Shutting down...'; kill $BACKEND_PID $FRONTEND_PID; exit 0" INT

wait
