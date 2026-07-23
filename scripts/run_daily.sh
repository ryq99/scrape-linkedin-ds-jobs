#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_daily.sh — Run the LinkedIn job scraper locally.
#
# Usage:
#   ./scripts/run_daily.sh                 # daily incremental scrape (past 24h)
#   ./scripts/run_daily.sh --headed        # visible browser (for debugging)
#   ./scripts/run_daily.sh --sleep-after   # put the Mac to sleep when done
#                                          # (used by the launchd overnight job)
#
# The scrape runs under `caffeinate` so idle sleep can't tear the browser down
# mid-run. `--sleep-after` returns the Mac to sleep once the run + upload finish;
# omit it for manual daytime runs so your machine isn't slept out from under you.
#
# Scheduled via launchd: see infra/linkedin-scraper.plist.example
# ---------------------------------------------------------------------------

set -euo pipefail

# Pull our own --sleep-after flag out of the args before forwarding the rest to
# python (main.py uses argparse and would reject an unknown flag).
SLEEP_AFTER=0
ARGS=()
for arg in "$@"; do
    if [[ "$arg" == "--sleep-after" ]]; then
        SLEEP_AFTER=1
    else
        ARGS+=("$arg")
    fi
done

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
# `caffeinate -i` holds an idle-sleep assertion for the lifetime of the scrape
# (released automatically when python exits) — this is what stops the Mac from
# sleeping mid-run and killing the browser subprocess.
# `|| EXIT_CODE=$?` keeps set -e from aborting before the footer logs on failure.
EXIT_CODE=0
caffeinate -i python3 src/main.py scrape ${ARGS[@]+"${ARGS[@]}"} || EXIT_CODE=$?

echo "===== Scraper finished at $(date -u '+%Y-%m-%d %H:%M:%S UTC') (exit $EXIT_CODE) ====="

if [[ "$SLEEP_AFTER" -eq 1 ]]; then
    echo "Returning to sleep (pmset sleepnow)."
    pmset sleepnow || true
fi

exit $EXIT_CODE
