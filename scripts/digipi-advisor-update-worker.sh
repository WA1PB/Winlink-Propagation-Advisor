#!/bin/bash
# Winlink Advisor background worker.
# Runs as pi; the installed root-owned controller launches it.

set -Eeuo pipefail

REPO="/home/pi/winlink-advisor"
STATE_DIR="/var/tmp/winlink-advisor-update"
LOCK_FILE="$STATE_DIR/update.lock"
LOG_FILE="$STATE_DIR/update.log"
RESULT_FILE="$STATE_DIR/result"
PID_FILE="$STATE_DIR/pid"

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

[[ "$(id -un)" == "pi" ]] ||
    fail "The update worker must run as pi."

case "${1:-}" in

    launch-test|launch-update)
        mkdir -p "$STATE_DIR"

        # Acquire the lock before launching the background worker.
        exec 9>"$LOCK_FILE"
        flock -n 9 || fail "An Advisor update is already running."

        : > "$LOG_FILE"
        printf 'RUNNING\n' > "$RESULT_FILE"

        if [[ "$1" == "launch-test" ]]; then
            worker_mode="run-test"
        else
            worker_mode="run-update"
        fi

        nohup "$0" "$worker_mode" 9>&9 \
            >> "$LOG_FILE" 2>&1 </dev/null &

        worker_pid=$!
        printf '%s\n' "$worker_pid" > "$PID_FILE"

        echo "Background worker started."
        echo "PID: $worker_pid"
        ;;

    run-test)
        # The inherited lock remains held throughout the test.
        echo "Simulated update started at $(date)"
        echo "No GitHub fetch or installation changes will occur."
        sleep 4
        echo "Simulated update completed at $(date)"
        printf 'TEST COMPLETED SUCCESSFULLY\n' > "$RESULT_FILE"
        ;;

    run-update)
        # The inherited lock remains held throughout the real update.
        echo "Advisor update started at $(date)"

        if [[ ! -x "$REPO/update.sh" ]]; then
            echo "ERROR: The existing update.sh is missing or not executable."
            printf 'UPDATE FAILED\n' > "$RESULT_FILE"
            exit 1
        fi

        cd "$REPO"

        if ./update.sh; then
            echo "Advisor update completed at $(date)"
            printf 'UPDATE COMPLETED SUCCESSFULLY\n' > "$RESULT_FILE"
        else
            update_rc=$?
            echo "ERROR: update.sh exited with status $update_rc"
            printf 'UPDATE FAILED (exit %s)\n' "$update_rc" > "$RESULT_FILE"
            exit "$update_rc"
        fi
        ;;

    *)
        fail "Invalid worker operation."
        ;;
esac
