#!/usr/bin/env bash
# Worldview launcher — idempotent.
#
# Run this from anywhere; it cd's to the repo root, sets up the venv if
# missing, installs/refreshes dependencies on demand, sanity-checks .env
# and the SQLite store, optionally seeds with a first snapshot, and then
# starts the FastAPI app on localhost.
#
# Usage:
#   ./start.sh                     # default port 8000
#   PORT=9000 ./start.sh           # pick a different port
#   ./start.sh --no-seed           # skip the auto initial snapshot
#   ./start.sh --reinstall         # force `pip install -e .[dev]` again

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ── Args ──────────────────────────────────────────────────────────────────────
NO_SEED=0
REINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --no-seed)   NO_SEED=1 ;;
    --reinstall) REINSTALL=1 ;;
    -h|--help)
      sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg"; exit 2 ;;
  esac
done

step() { printf "\033[1;36m→\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m✓\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m⚠\033[0m %s\n" "$*"; }
die()  { printf "\033[1;31m✗\033[0m %s\n" "$*" >&2; exit 1; }

# ── 1. Python ─────────────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
  die "python3 not found on PATH. Install Python ≥3.11 first."
fi
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3,11) else 0)')
[ "$PY_OK" = "1" ] || die "Worldview needs Python ≥ 3.11 (you have $PY_VER)."
ok "python3 $PY_VER"

# ── 2. venv ───────────────────────────────────────────────────────────────────
if [ ! -d .venv ]; then
  step "Creating .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
ok "venv active ($(python -V 2>&1))"

# ── 3. deps ───────────────────────────────────────────────────────────────────
DEP_STAMP=".venv/.deps_installed"
NEED_INSTALL=0
if [ "$REINSTALL" = "1" ] || [ ! -f "$DEP_STAMP" ]; then
  NEED_INSTALL=1
elif [ pyproject.toml -nt "$DEP_STAMP" ]; then
  NEED_INSTALL=1
fi
if [ "$NEED_INSTALL" = "1" ]; then
  step "Installing dependencies (one-time / on pyproject change)"
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet -e ".[dev]"
  touch "$DEP_STAMP"
fi
ok "dependencies up to date"

# ── 4. .env ───────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  step "Creating .env from template"
  cp .env.example .env
  warn ".env created — add FRED_API_KEY (free at https://fred.stlouisfed.org/docs/api/api_key.html)"
fi
if grep -Eq '^FRED_API_KEY=.+' .env; then
  ok "FRED_API_KEY present"
else
  warn "FRED_API_KEY blank in .env — most macro metrics will be skipped until set"
fi

# ── 5. DB + initial snapshot ──────────────────────────────────────────────────
DB_PATH="${WORLDVIEW_DB_PATH:-$ROOT/worldview/store/worldview.db}"
if [ ! -f "$DB_PATH" ]; then
  step "Initializing SQLite store at $DB_PATH"
  python -m worldview.cli init-db
fi
ROW_COUNT=$(python -c "import sqlite3, sys; sys.stdout.write(str(sqlite3.connect('$DB_PATH').execute('SELECT COUNT(*) FROM observations').fetchone()[0]))")
if [ "$ROW_COUNT" = "0" ] && [ "$NO_SEED" = "0" ]; then
  step "Empty DB — seeding with a monthly snapshot (first run takes ~1 min)"
  python -m worldview.cli snapshot --cadence monthly || warn "Initial snapshot had failures — dashboard will still work with whatever did succeed."
  ok "Initial seed done. Re-run later via the in-app Refresh button."
else
  ok "DB has $ROW_COUNT observation rows"
fi

# ── 6. uvicorn ────────────────────────────────────────────────────────────────
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
echo
step "Starting Worldview at http://${HOST}:${PORT}"
echo "  (Ctrl-C to stop. Tests: 'pytest -q'  ·  Manual snapshot: 'python -m worldview.cli snapshot --cadence daily')"
echo
exec uvicorn worldview.webapp.main:app --host "$HOST" --port "$PORT" --reload
