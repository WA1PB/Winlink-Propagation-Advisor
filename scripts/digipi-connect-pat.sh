#!/bin/bash
# Winlink Advisor: start DigiPi ARDOP and PAT.
# This controller does not select a gateway or initiate a connection.

set -u

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

if [[ $EUID -ne 0 ]]; then
    fail "Run this controller through sudo."
fi

if [[ $# -ne 0 ]]; then
    fail "This ARDOP-only controller accepts no arguments."
fi

command -v systemctl >/dev/null 2>&1 ||
    fail "systemctl was not found."

echo "Starting ARDOP service..."
if ! systemctl start ardop.service; then
    fail "Could not start ardop.service. Check: journalctl -u ardop.service"
fi

# Allow the modem service time to initialize.
ardop_ready=0
for ((i = 0; i < 15; i++)); do
    if systemctl is-active --quiet ardop.service; then
        ardop_ready=1
        break
    fi
    sleep 1
done

if [[ $ardop_ready -ne 1 ]]; then
    systemctl --no-pager --full status ardop.service || true
    fail "ARDOP did not become active. PAT was not started."
fi

echo "ARDOP: active"
echo "Starting PAT service..."

if ! systemctl start pat.service; then
    systemctl --no-pager --full status pat.service || true
    fail "Could not start pat.service. Check: journalctl -u pat.service"
fi

pat_ready=0
for ((i = 0; i < 15; i++)); do
    if systemctl is-active --quiet pat.service; then
        pat_ready=1
        break
    fi
    sleep 1
done

if [[ $pat_ready -ne 1 ]]; then
    systemctl --no-pager --full status pat.service || true
    fail "PAT did not become active. ARDOP has been left running."
fi

echo "PAT: active"
echo "Connect PAT complete"
echo "Open the PAT web interface at http://<DigiPi-address>:8080/ui"
echo "No gateway was selected or connected."
exit 0
