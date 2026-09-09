#!/bin/sh
# Rybbit tester-env analytics reseed helper.
# Lives at tester-env-seed/reset-and-seed.sh inside the fork; the ./tester-env
# CLI calls seed.py/verify.py directly. Kept for manual analytics-only reseeds.
# Usage: sh reset-and-seed.sh [--days 14]
# Full stack reset goes through the CLI: ./tester-env reset && ./tester-env deploy
# (then browser signup tester@example.com/TestPass123!, Test Org, example.com).
set -eu
DAYS="${1:-14}"
BASE_URL="${BASE_URL:-http://172.17.0.1:3001}"
HERE="$(dirname "$0")"

python3 "$HERE/seed.py" --base-url "$BASE_URL" --site-id 1 --days "$DAYS"
python3 "$HERE/verify.py" --base-url "$BASE_URL" --site-id 1
