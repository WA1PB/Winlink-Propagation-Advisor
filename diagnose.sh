#!/bin/bash
# Winlink Advisor read-only diagnostic.
# Does not start/stop services or change configuration.

set -u
cd /home/pi/winlink-advisor || exit 1

exec python3 -B - <<'PYTHON'
import ast
import contextlib
import importlib.util
import io
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

results = []

def report(status, name, detail):
    results.append(status)
    print(f"[{status}] {name}: {detail}")

def command_output(args, timeout=10):
    try:
        return subprocess.run(
            args, capture_output=True, text=True,
            timeout=timeout, check=False
        )
    except Exception as exc:
        return None

print("=" * 58)
print("WINLINK PROPAGATION ADVISOR — READ-ONLY DIAGNOSTICS")
print("=" * 58)
print("No configuration changes or service start/stop actions.")
print("API keys and other secret values are not displayed.")
print()

root = Path("/home/pi/winlink-advisor")
config_path = Path("/home/pi/localize.env")
source = root / "advisor.py"
web_source = root / "web/winlink-advisor.php"
live_web = Path("/var/www/html/winlink-advisor.php")
controller = Path("/usr/local/bin/digipi-connect-pat.sh")

# Installation and dependencies
if source.is_file():
    report("PASS", "Advisor engine", "Source file exists")
else:
    report("FAIL", "Advisor engine", "advisor.py is missing")

if web_source.is_file() and live_web.is_file():
    report("PASS", "Dashboard files", "Source and installed PHP page exist")
elif web_source.is_file() or live_web.is_file():
    report("WARNING", "Dashboard files", "One dashboard file is missing")
else:
    report("FAIL", "Dashboard files", "Dashboard source and installed page are missing")

help_file = Path("/var/www/html/winlink-advisor-help.txt")
report(
    "PASS" if help_file.is_file() else "WARNING",
    "Help page",
    "Installed help file exists" if help_file.is_file()
    else "Installed help file was not found"
)

missing = [name for name in ("python3", "php", "curl", "getent", "systemctl")
           if shutil.which(name) is None]
report(
    "PASS" if not missing else "FAIL",
    "Required commands",
    "Python, PHP, curl, getent and systemctl are available"
    if not missing else "Missing: " + ", ".join(missing)
)

try:
    ast.parse(source.read_text())
    report("PASS", "Python syntax", "Advisor engine parses successfully")
except Exception as exc:
    report("FAIL", "Python syntax", f"Advisor source could not be parsed: {type(exc).__name__}")

if live_web.is_file() and shutil.which("php"):
    result = command_output(["php", "-l", str(live_web)])
    if result and result.returncode == 0:
        report("PASS", "PHP syntax", "Installed dashboard passes php -l")
    else:
        report("FAIL", "PHP syntax", "Installed dashboard failed php -l")
else:
    report("WARNING", "PHP syntax", "Skipped because PHP or dashboard file is missing")

# Configuration: report presence/format only, never print values such as WINLINK_KEY.
config = {}
try:
    for line in config_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            if key in ("NEWCALL", "NEWGRID"):
                config[key] = value.strip().strip("'\"")
    report("PASS", "Station configuration", "Configuration file is readable")
except Exception:
    report("FAIL", "Station configuration", "Could not read station configuration")

callsign = config.get("NEWCALL", "")
grid = config.get("NEWGRID", "").upper()

if callsign and re.fullmatch(r"[A-Z0-9/]{3,12}", callsign.upper()):
    report("PASS", "Station callsign", "Present and format looks valid")
else:
    report("FAIL", "Station callsign", "NEWCALL is missing or has an unexpected format")

if re.fullmatch(r"[A-R]{2}[0-9]{2}([A-X]{2})?", grid):
    report("PASS", "Station grid", "Present and format looks valid")
else:
    report("FAIL", "Station grid", "NEWGRID is missing or has an unexpected format")

# PAT / ARDOP: read current service state only.
if controller.is_file() and os.access(controller, os.X_OK):
    report("PASS", "PAT controller", "Controller exists and is executable")
else:
    report("WARNING", "PAT controller", "Controller is missing or not executable")

for service in ("ardop.service", "pat.service"):
    result = command_output(["systemctl", "is-active", service])
    state = result.stdout.strip() if result else "unknown"
    if state == "active":
        report("PASS", service, "Currently active")
    elif state in ("inactive", "failed", "activating", "deactivating"):
        report("WARNING", service, f"Current state is {state}; no action taken")
    else:
        report("WARNING", service, f"Could not confirm service state ({state or 'unknown'})")

# DNS checks
for host in ("pskreporter.info", "api.winlink.org"):
    try:
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        report("PASS", f"DNS {host}", "Hostname resolved")
    except Exception:
        report("WARNING", f"DNS {host}", "Could not resolve hostname")

# Load the existing engine and test its existing data-fetch functions.
# Capture their normal output so gateway listings and key-related text
# cannot be accidentally included in this diagnostic report.
if source.is_file() and callsign:
    try:
        spec = importlib.util.spec_from_file_location("advisor_diagnostic", source)
        advisor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(advisor)
    except Exception as exc:
        advisor = None
        report("FAIL", "Advisor module", f"Could not load engine ({type(exc).__name__})")
else:
    advisor = None

if advisor:
    try:
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            channels = advisor.fetch_winlink_channels("")
        fetch_output = captured.getvalue()
        if channels:
            report("PASS", "Public Winlink gateway API",
                   f"Retrieved {len(channels)} eligible channel records")
        elif "WINLINK API ERROR" in fetch_output:
            report("WARNING", "Public Winlink gateway API",
                   "Request failed; check network access or API availability")
        else:
            report("WARNING", "Public Winlink gateway API",
                   "Request completed but returned no eligible channels")
    except Exception as exc:
        report("WARNING", "Public Winlink gateway API",
               f"Could not complete check ({type(exc).__name__})")

    try:
        with contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            reports = advisor.fetch_wspr_reports(callsign)
        if reports:
            report("PASS", "PSKReporter WSPR data",
                   f"Retrieved {len(reports)} reports for configured callsign")
        else:
            report("WARNING", "PSKReporter WSPR data",
                   "No reports returned; this can be normal when recent spots are unavailable")
    except Exception as exc:
        report("WARNING", "PSKReporter WSPR data",
               f"Request failed or timed out ({type(exc).__name__})")
else:
    report("WARNING", "Public Winlink gateway API", "Skipped because engine could not be loaded")
    report("WARNING", "PSKReporter WSPR data", "Skipped because engine could not be loaded")

print()
print("=" * 58)
print("SUMMARY")
print(f"PASS: {results.count('PASS')}   WARNING: {results.count('WARNING')}   FAIL: {results.count('FAIL')}")
if "FAIL" in results:
    print("Result: One or more checks failed; review the lines above.")
elif "WARNING" in results:
    print("Result: Core checks completed; review warnings above.")
else:
    print("Result: All checks passed.")
print("=" * 58)
PYTHON
