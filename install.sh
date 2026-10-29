#!/bin/bash
set -euo pipefail

# Winlink Propagation Advisor installer
# Installs the Advisor engine and web interface on a DigiPi.
# Installs a controller for starting existing ARDOP and PAT services on request.
# Does not install or configure PAT/Mercury/VARA/ARDOP or start them during installation.

INSTALL_DIR="/home/pi/winlink-advisor"
WEB_DIR="/var/www/html"
BACKUP_DIR="$INSTALL_DIR/backups"
CONFIG_FILE="/home/pi/localize.env"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo " Winlink Propagation Advisor Installer"
echo "========================================"
echo

if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: Run this installer with sudo."
    echo "Example: sudo ./install.sh"
    exit 1
fi

# DigiPi normally uses a read-only root filesystem.
# Remount read-write before installing files or creating backups.
echo "Ensuring DigiPi filesystem is writable..."

if ! command -v remount >/dev/null 2>&1; then
    echo "ERROR: DigiPi remount command was not found."
    exit 1
fi

if ! remount; then
    echo "ERROR: Could not remount DigiPi filesystem read-write."
    exit 1
fi

if ! findmnt -no OPTIONS / | tr "," "\n" | grep -qx rw; then
    echo "ERROR: Root filesystem is still read-only."
    exit 1
fi

echo "Filesystem is writable."
echo

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ERROR: $CONFIG_FILE was not found."
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 was not found."
    exit 1
fi

if ! command -v php >/dev/null 2>&1; then
    echo "ERROR: php was not found."
    exit 1
fi

for required_file in \
    "$SCRIPT_DIR/advisor.py" \
    "$SCRIPT_DIR/web/winlink-advisor.php" \
    "$SCRIPT_DIR/docs/winlink-advisor-help.txt" \
    "$SCRIPT_DIR/web/assets/misty-mountain-sunset.png" \
    "$SCRIPT_DIR/scripts/digipi-connect-pat.sh" \
    "$SCRIPT_DIR/scripts/digipi-advisor-update.sh" \
    "$SCRIPT_DIR/scripts/digipi-advisor-update-worker.sh"
do
    if [[ ! -f "$required_file" ]]; then
        echo "ERROR: Required package file missing:"
        echo "  $required_file"
        exit 1
    fi
done

NEWCALL=""
NEWGRID=""
WINLINK_KEY=""

while IFS='=' read -r key value; do
    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"

    case "$key" in
        NEWCALL) NEWCALL="$value" ;;
        NEWGRID) NEWGRID="$value" ;;
        WINLINK_KEY) WINLINK_KEY="$value" ;;
    esac
done < "$CONFIG_FILE"

if [[ -z "$NEWCALL" || -z "$NEWGRID" ]]; then
    echo "ERROR: localize.env must contain NEWCALL and NEWGRID."
    exit 1
fi

echo "Station configuration:"
echo "  Callsign: $NEWCALL"
echo "  Grid:     $NEWGRID"

if [[ -n "$WINLINK_KEY" ]]; then
    echo "  Key:      present"
else
    echo "  Key:      not present"
    echo "  INFO: Public gateway access will be used when WINLINK_KEY is absent."
fi

echo
echo "Checking package..."

python3 -m py_compile "$SCRIPT_DIR/advisor.py"

echo "Package checks passed."

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

if [[ -f "$INSTALL_DIR/advisor.py" || \
      -f "$WEB_DIR/winlink-advisor.php" || \
      -f "$WEB_DIR/winlink-advisor-help.txt" || \
      -f "$WEB_DIR/winlink-advisor-assets/misty-mountain-sunset.png" || \
      -f /usr/local/bin/digipi-connect-pat.sh || \
      -f /usr/local/bin/digipi-advisor-update.sh || \
      -f /usr/local/bin/digipi-advisor-update-worker.sh ]]; then

    mkdir -p "$BACKUP_DIR/$TIMESTAMP"

    echo
    echo "Existing Advisor installation found."
    echo "Creating backup: $BACKUP_DIR/$TIMESTAMP"

    if [[ -f "$INSTALL_DIR/advisor.py" ]]; then
        cp -a "$INSTALL_DIR/advisor.py" "$BACKUP_DIR/$TIMESTAMP/"
    fi

    if [[ -f "$WEB_DIR/winlink-advisor.php" ]]; then
        cp -a "$WEB_DIR/winlink-advisor.php" "$BACKUP_DIR/$TIMESTAMP/"
    fi

    if [[ -f "$WEB_DIR/winlink-advisor-help.txt" ]]; then
        cp -a "$WEB_DIR/winlink-advisor-help.txt" "$BACKUP_DIR/$TIMESTAMP/"
    fi

    if [[ -f "$WEB_DIR/winlink-advisor-assets/misty-mountain-sunset.png" ]]; then
        cp -a "$WEB_DIR/winlink-advisor-assets/misty-mountain-sunset.png" "$BACKUP_DIR/$TIMESTAMP/"
    fi

    if [[ -f /usr/local/bin/digipi-connect-pat.sh ]]; then
        cp -a /usr/local/bin/digipi-connect-pat.sh "$BACKUP_DIR/$TIMESTAMP/"
    fi

    if [[ -f /usr/local/bin/digipi-advisor-update.sh ]]; then
        cp -a /usr/local/bin/digipi-advisor-update.sh "$BACKUP_DIR/$TIMESTAMP/"
    fi

    if [[ -f /usr/local/bin/digipi-advisor-update-worker.sh ]]; then
        cp -a /usr/local/bin/digipi-advisor-update-worker.sh "$BACKUP_DIR/$TIMESTAMP/"
    fi
fi

echo
echo "Installing Advisor..."

mkdir -p "$INSTALL_DIR"
mkdir -p "$WEB_DIR"

if [[ "$SCRIPT_DIR/advisor.py" -ef "$INSTALL_DIR/advisor.py" ]]; then
    chmod 0755 "$INSTALL_DIR/advisor.py"
else
    install -m 0755 "$SCRIPT_DIR/advisor.py" "$INSTALL_DIR/advisor.py"
fi
install -m 0644 \
    "$SCRIPT_DIR/web/winlink-advisor.php" \
    "$WEB_DIR/winlink-advisor.php"

install -m 0644 \
    "$SCRIPT_DIR/docs/winlink-advisor-help.txt" \
    "$WEB_DIR/winlink-advisor-help.txt"

mkdir -p "$WEB_DIR/winlink-advisor-assets"
install -m 0644 \
    "$SCRIPT_DIR/web/assets/misty-mountain-sunset.png" \
    "$WEB_DIR/winlink-advisor-assets/misty-mountain-sunset.png"

install -m 0755 \
    "$SCRIPT_DIR/scripts/digipi-connect-pat.sh" \
    /usr/local/bin/digipi-connect-pat.sh

install -m 0755 \
    "$SCRIPT_DIR/scripts/digipi-advisor-update.sh" \
    /usr/local/bin/digipi-advisor-update.sh

install -m 0755 \
    "$SCRIPT_DIR/scripts/digipi-advisor-update-worker.sh" \
    /usr/local/bin/digipi-advisor-update-worker.sh

chown root:root /usr/local/bin/digipi-connect-pat.sh
chown root:root /usr/local/bin/digipi-advisor-update.sh
chown root:root /usr/local/bin/digipi-advisor-update-worker.sh

# State is deliberately writable by pi only.
install -d -o pi -g pi -m 0755 /var/tmp/winlink-advisor-update

chown pi:pi "$INSTALL_DIR/advisor.py"
chown root:root "$WEB_DIR/winlink-advisor.php"
chown root:root "$WEB_DIR/winlink-advisor-help.txt"
chown root:root "$WEB_DIR/winlink-advisor-assets/misty-mountain-sunset.png"

echo
echo "Running installed-copy self-test..."

PYTHONPATH="$INSTALL_DIR" python3 - <<'PY'
import advisor

tests = [
    ("West", 40, -120),
    ("Central", 40, -100),
    ("East", 40, -75),
    ("Europe / Atlantic", 50, 0),
    ("Europe / Africa", 45, 20),
]

for expected, lat, lon in tests:
    actual = advisor.classify_region(lat, lon)
    if actual != expected:
        print(f"FAIL: {lat}, {lon} -> {actual} (expected {expected})")
        raise SystemExit(1)
    print(f"OK: {lat}, {lon} -> {actual}")

print("Regional classification test passed.")
PY

echo
echo "Checking PHP syntax..."

php -l "$WEB_DIR/winlink-advisor.php"

echo
echo "Checking installed files..."

[[ -x "$INSTALL_DIR/advisor.py" ]]
[[ -f "$WEB_DIR/winlink-advisor.php" ]]
[[ -f "$WEB_DIR/winlink-advisor-help.txt" ]]
[[ -s "$WEB_DIR/winlink-advisor-assets/misty-mountain-sunset.png" ]]
[[ -x /usr/local/bin/digipi-connect-pat.sh ]]
[[ -x /usr/local/bin/digipi-advisor-update.sh ]]
[[ -x /usr/local/bin/digipi-advisor-update-worker.sh ]]
[[ -d /var/tmp/winlink-advisor-update ]]
[[ "$(stat -c '%U:%G %a' /var/tmp/winlink-advisor-update)" == "pi:pi 755" ]]

echo "Installed files verified, including the background image, PAT controller, and update controller."

# Add Winlink Advisor to the DigiPi home-page navigation.
INDEX_FILE="$WEB_DIR/index.php"

if [[ -f "$INDEX_FILE" ]]; then
    if grep -q 'href="/winlink-advisor.php"' "$INDEX_FILE"; then
        echo "DigiPi home-page link already exists."
    else
        python3 - "$INDEX_FILE" <<'PYINDEX'
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()

marker = """  <td>
    <a href="/wifi.php" title="Setup Wifi connection"><strong>Wifi</strong></a>
  </td>
"""

link = """  <td>
    <a href="/winlink-advisor.php" target="winlink-advisor" title="Winlink Propagation Advisor"><strong>Winlink Advisor</strong></a>
  </td>
"""

if marker not in s:
    print("WARNING: Could not locate the expected navigation entry.")
    print("Add the Winlink Advisor link manually if needed.")
else:
    p.write_text(s.replace(marker, marker + link, 1))
    print("Added Winlink Advisor to the DigiPi home page.")
PYINDEX
    fi
else
    echo "WARNING: DigiPi index.php not found; home-page link was not added."
fi

echo
echo "========================================"
echo " Installation completed successfully."
echo "========================================"
echo
echo "Advisor: $INSTALL_DIR/advisor.py"
echo "Web UI:  $WEB_DIR/winlink-advisor.php"
echo "Help:    $WEB_DIR/winlink-advisor-help.txt"
echo

if [[ -x /usr/local/bin/digipi-connect-pat.sh ]]; then
    echo "PAT integration: start controller installed."
fi

echo
echo "PAT and ARDOP services were not started during installation."
echo "Use Start ARDOP + PAT on the dashboard to start existing services."
echo "Gateway selection and connection remain manual in PAT."
echo
