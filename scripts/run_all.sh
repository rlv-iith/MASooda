#!/usr/bin/env sh
# One-command Week 6 pipeline (workflow 14.8). Same arguments as scripts/run_all.py:
#   scripts/run_all.sh [--quick] [--only e1,e4] [--skip-video] [--workers N] [--fresh]
set -eu
cd "$(dirname "$0")/.."
if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
else
  PY="python3"
fi
exec "$PY" scripts/run_all.py "$@"
