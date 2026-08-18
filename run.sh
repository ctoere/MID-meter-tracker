#!/usr/bin/env bash
# Start the Zeres MID Register. Builds the register on first run.
set -euo pipefail
cd "$(dirname "$0")"

if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [ ! -f data/Zeres_MID_Register.xlsx ]; then
  echo "No register yet — running the one-time migration..."
  python -m migrate.migrate_tracker
fi

exec python -m app
