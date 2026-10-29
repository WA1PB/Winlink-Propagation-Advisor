#!/bin/bash
# Winlink Advisor update controller.
# Installed as root-owned; accepts only fixed operations.

set -Eeuo pipefail

WORKER="/usr/local/bin/digipi-advisor-update-worker.sh"
STATE_DIR="/var/tmp/winlink-advisor-update"
LOCK_FILE="$STATE_DIR/update.lock"
LOG_FILE="$STATE_DIR/update.log"
RESULT_FILE="$STATE_DIR/result"

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

# The installed controller must run as root.
[[ "$EUID" -eq 0 ]] || fail "Run this controller through sudo."
[[ "$#" -eq 1 ]] || fail "Usage: $0 {start|status|test}"

case "$1" in
    status)
        echo "===== UPDATE STATUS ====="

        if [[ -f "$LOCK_FILE" ]] && ! flock -n "$LOCK_FILE" -c true 2>/dev/null; then
            echo "RUNNING"
        else
            echo "NOT RUNNING"
        fi

        echo
        echo "===== LAST RESULT ====="
        if [[ -f "$RESULT_FILE" ]]; then
            cat "$RESULT_FILE"
        else
            echo "No update result recorded."
        fi

        echo
        echo "===== RECENT LOG ====="
        if [[ -f "$LOG_FILE" ]]; then
            tail -100 "$LOG_FILE"
        else
            echo "No update log recorded."
        fi
        ;;

    test)
        [[ -x "$WORKER" ]] || fail "Installed update worker is missing."
        sudo -u pi "$WORKER" launch-test
        ;;

    start)
        [[ -x "$WORKER" ]] || fail "Installed update worker is missing."
        [[ -x "/home/pi/winlink-advisor/update.sh" ]] ||
            fail "The existing update.sh is missing or not executable."

        sudo -u pi "$WORKER" launch-update
        ;;

    *)
        fail "Usage: $0 {start|status|test}"
        ;;
esac
