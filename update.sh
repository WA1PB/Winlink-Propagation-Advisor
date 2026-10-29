#!/bin/bash
set -Eeuo pipefail

REPO="/home/pi/winlink-advisor"
BACKUP_ROOT="/home/pi/winlink-advisor-update-backups"
INSTALL_DIR="/home/pi/winlink-advisor"
WEB_DIR="/var/www/html"
EXPECTED_REMOTE="https://github.com/WA1PB/Winlink-Propagation-Advisor.git"

step=0

log() {
    printf '\n[%s] %s\n' "$1" "$2"
}

fail() {
    echo
    echo "ERROR: $*" >&2
    echo "The update stopped. Review the message above before trying again." >&2
    exit 1
}

if [[ "${EUID}" -eq 0 ]]; then
    fail "Run this script as user pi, without sudo. It will request sudo when needed."
fi

if [[ "$(id -un)" != "pi" ]]; then
    fail "This updater is designed for the DigiPi user pi."
fi

if [[ ! -d "$REPO/.git" ]]; then
    fail "$REPO is not a Git repository."
fi

cd "$REPO"

echo "========================================"
echo " Winlink Advisor Updater"
echo "========================================"
echo "Repository: $REPO"
echo

log "1/7" "Checking repository and filesystem..."

remote="$(git remote get-url origin)" ||
    fail "Could not read the origin Git remote."

if [[ "$remote" != "$EXPECTED_REMOTE" ]]; then
    fail "Unexpected Git remote: $remote"
fi

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    git status --short
    fail "Tracked files have local changes. Commit or back them up before updating."
fi

if ! command -v sudo >/dev/null 2>&1; then
    fail "sudo is not available."
fi

log "2/7" "Remounting DigiPi filesystem for writing..."

sudo remount ||
    fail "Could not remount the filesystem."

if ! touch "$REPO/.update-write-test" 2>/dev/null; then
    fail "The repository filesystem is still not writable."
fi
rm -f "$REPO/.update-write-test"

timestamp="$(date +%Y%m%d-%H%M%S)"
backup="$BACKUP_ROOT/$timestamp"

log "3/7" "Creating timestamped backups..."

mkdir -p "$backup"

# Back up the repository while excluding Git internals and previous backups.
tar -czf "$backup/repository.tar.gz" \
    --exclude='./.git' \
    --exclude='./backups' \
    --exclude='./update-backups' \
    -C "$REPO" . ||
    fail "Repository backup failed. No update was attempted."

# Back up currently installed web files and the DigiPi home page.
sudo tar -czf "$backup/installed-files.tar.gz" \
    --ignore-failed-read \
    -C / \
    home/pi/winlink-advisor/advisor.py \
    var/www/html/winlink-advisor.php \
    var/www/html/winlink-advisor-help.txt \
    var/www/html/winlink-advisor-assets/misty-mountain-sunset.png \
    var/www/html/index.php ||
    fail "Installed-file backup failed. No update was attempted."

# Verify that both archives can be read.
tar -tzf "$backup/repository.tar.gz" >/dev/null ||
    fail "Repository backup verification failed."

sudo tar -tzf "$backup/installed-files.tar.gz" >/dev/null ||
    fail "Installed-file backup verification failed."

echo "Backups created in: $backup"

log "4/7" "Fetching the latest GitHub version..."

git fetch origin ||
    fail "Could not fetch from GitHub. Check network connectivity."

if ! git show-ref --verify --quiet refs/remotes/origin/main; then
    fail "Could not find origin/main."
fi

target="$(git rev-parse origin/main)"
echo "Target commit: $target"

log "5/7" "Updating repository files..."

git reset --hard origin/main ||
    fail "Git could not update the repository. Backup: $backup"

log "6/7" "Running the installer..."

sudo ./install.sh ||
    fail "The installer failed. Review its output. Backups: $backup"

log "7/7" "Verifying the updated installation..."

[[ -x "$INSTALL_DIR/advisor.py" ]] ||
    fail "Installed advisor.py is missing or not executable."

[[ -f "$WEB_DIR/winlink-advisor.php" ]] ||
    fail "Installed web interface is missing."

[[ -f "$WEB_DIR/winlink-advisor-help.txt" ]] ||
    fail "Installed help file is missing."

python3 -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text())' "$INSTALL_DIR/advisor.py" ||
    fail "The installed Python file failed syntax validation."

echo
echo "========================================"
echo " UPDATE COMPLETED SUCCESSFULLY"
echo "========================================"
echo "Installed commit: $(git rev-parse --short HEAD)"
echo "Backup directory: $backup"
echo
echo "Please open Winlink Advisor in your browser"
echo "and verify that the page and data load."
echo
echo "Note: Successful installation does not by itself"
echo "confirm that fresh PSK Reporter data is available."
