#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_daily.sh — Run the LinkedIn job scraper locally.
#
# Usage:
#   ./scripts/run_daily.sh              # uses defaults in .env
#   ./scripts/run_daily.sh --no-headless  # open visible browser (for debugging)
#
# Cron example (every day at 10 pm):
#   0 22 * * * /path/to/ds_jobs/scripts/run_daily.sh >> /path/to/ds_jobs/logs/scrape.log 2>&1
# ---------------------------------------------------------------------------

set -euo pipefail

# ── Resolve the project root (works whether called from any cwd) ──────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "===== LinkedIn scraper started at $(date -u '+%Y-%m-%d %H:%M:%S UTC') ====="
echo "Project: $PROJECT_DIR"

# ── Activate virtualenv if present ───────────────────────────────────────────
VENV="$PROJECT_DIR/.venv"
if [[ -d "$VENV" ]]; then
    echo "Activating virtualenv: $VENV"
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
fi

# ── Run the scraper ───────────────────────────────────────────────────────────
cd "$PROJECT_DIR"

python3 src/scrape.py \
    --prompt "${SCRAPE_PROMPT:-AI/ML Data Scientist at tech companies}" \
    --num-pages "${NUM_PAGES:-10}" \
    --headless \
    "$@"   # pass any extra CLI flags straight through (e.g. --no-hf, --no-s3)

EXIT_CODE=$?
echo "===== Scraper finished at $(date -u '+%Y-%m-%d %H:%M:%S UTC') (exit $EXIT_CODE) ====="
exit $EXIT_CODE
