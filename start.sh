#!/usr/bin/env bash
# Start Whats-News locally (one command for friends / Caspar).
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8050}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install it, then run this script again."
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "Creating a local virtualenv (.venv)…"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "Installing / updating dependencies…"
python -m pip install -q -r requirements.txt

echo ""
echo "  Whats-News"
echo "  Dashboard → http://localhost:${PORT}"
echo "  News      → http://localhost:${PORT}/news"
echo "  Press Ctrl+C to stop."
echo ""

export PORT
# One-process default: analysis talks to local SQLite (no :8051 required).
export DATA_SERVICE_MODE="${DATA_SERVICE_MODE:-embedded}"
exec python app.py
