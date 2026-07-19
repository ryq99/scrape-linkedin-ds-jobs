#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_daily.sh — Run the LinkedIn job scraper locally.
#
# Usage:
#   ./scripts/run_daily.sh              # daily incremental scrape (past 24h)
#   ./scripts/run_daily.sh --headed     # visible browser (for debugging)
#
# Scheduled via launchd: see infra/linkedin-scraper.plist.example
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "===== LinkedIn scraper started at $(date -u '+%Y-%m-%d %H:%M:%S UTC') ====="

VENV="$PROJECT_DIR/.venv"
if [[ -d "$VENV" ]]; then
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
fi

ENV_FILE="$PROJECT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a; source "$ENV_FILE"; set +a
fi

cd "$PROJECT_DIR"
python3 src/main.py scrape "$@"

EXIT_CODE=$?
echo "===== Scraper finished at $(date -u '+%Y-%m-%d %H:%M:%S UTC') (exit $EXIT_CODE) ====="
exit $EXIT_CODE
