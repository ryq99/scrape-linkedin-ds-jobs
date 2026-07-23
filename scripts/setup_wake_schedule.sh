#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup_wake_schedule.sh — install the daily wake that lets the scraper run
#                          unattended overnight.
#
# THIS IS THE PIECE launchd CANNOT DO. `StartCalendarInterval` in the plist
# only runs the job when the Mac is already awake (or on its next wake) — it
# does NOT wake a sleeping Mac. `pmset repeat wake` schedules an actual
# hardware wake event so the machine is awake when launchd fires at 22:00.
#
# Run ONCE, with sudo (pmset scheduling requires root):
#   sudo ./scripts/setup_wake_schedule.sh
#
# Undo:
#   sudo pmset repeat cancel
#
# Inspect the current schedule any time (no sudo needed):
#   pmset -g sched
# ---------------------------------------------------------------------------

set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
    echo "This script must be run with sudo (pmset scheduling requires root)." >&2
    echo "  sudo $0" >&2
    exit 1
fi

# Wake every day at 21:58, a 2-minute buffer before the 22:00 launchd job.
# MTWRFSU = Mon Tue Wed Thu Fri Sat Sun (every day).
pmset repeat wake MTWRFSU 21:58:00

echo "Daily wake installed. Current schedule:"
pmset -g sched
