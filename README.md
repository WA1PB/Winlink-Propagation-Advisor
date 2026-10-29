# Winlink Propagation Advisor

**Version 2.0.0**

A WSPR-based propagation dashboard for DigiPi that uses recent WSPR reception reports and Winlink gateway information to help identify potentially useful HF Winlink paths.

The Advisor is designed to run on a Raspberry Pi/DigiPi with a standard web server and Python 3.

## What It Does

Winlink Propagation Advisor combines:

- WSPR reception reports from PSKReporter
- Recent receiver and signal-strength information
- HF band selection
- Winlink HF gateway status
- VARA and ARDOP gateway information
- Broad propagation regions
- Freshness-aware recommendations
- Redesigned dashboard with a mountain-sunset background
- Callsign and grid square displayed together in the header
- Selectable Top 5, 10, 15, or 20 gateway recommendations
- Regional recommendations filtered to match the selected limit
- Start ARDOP + PAT button to start existing DigiPi services on request
- Open PAT Email link to the existing PAT web interface
- A browser-based DigiPi web interface

The Advisor emphasizes **recent propagation evidence** rather than relying only on static distance calculations.
## What It Does Not Install

The Advisor installer does not install or configure:

- PAT
- Mercury
- VARA HF
- ARDOP
- Hamlib
- Your radio
- WSPR/WSJT-X
- DigiPi's existing radio configuration

The installer also installs the small `digipi-connect-pat.sh` controller used by the dashboard's **Start ARDOP + PAT** button. Pressing the button requests that the existing `ardop.service` and `pat.service` start. It does not install or configure those services, select a gateway, or initiate a Winlink connection.

The button requires the relevant DigiPi services to be installed and the web server to be able to invoke the controller through the existing system permissions. The installer does not change DigiPi's sudo configuration or start radio services during installation.

This makes the Advisor suitable for installation on an existing DigiPi without changing the radio stack.

## Requirements

A normal DigiPi installation should already provide:

- Raspberry Pi / DigiPi
- Python 3
- PHP
- /home/pi/localize.env
- A working DigiPi web server

The installer expects the standard DigiPi configuration file:

    /home/pi/localize.env

with at least:

    NEWCALL=YOURCALL
    NEWGRID=YOURGRID

WINLINK_KEY is optional. Without it, the Advisor uses the public gateway access mechanism for Winlink HF channel information.

The installer never displays the actual Winlink key.

## Installation

Clone or copy this repository onto the DigiPi.

cd /home/pi
git clone https://github.com/WA1PB/Winlink-Propagation-Advisor.git winlink-advisor
cd winlink-advisor
sudo bash ./install.sh

The installer will:

1. Check the DigiPi configuration.
2. Check required software.
3. Validate the Advisor Python code.
4. Back up an existing Advisor installation.
5. Install the Advisor engine.
6. Install the web interface.
7. Install the help document.
8. Install the dashboard background image.
9. Install the ARDOP + PAT start controller.
10. Run regional classification self-tests.
11. Check PHP syntax.
12. Verify the installed files.
13. Add a Winlink Advisor link to the DigiPi home page, if it is not already present.

Existing installations are backed up under:

    /home/pi/winlink-advisor/backups/

Each backup receives a timestamped directory.

## Web Interface

After installation, open the DigiPi home page and click **Winlink Advisor**.

The installer adds this link automatically when it finds the expected DigiPi navigation entry. If the entry cannot be found, the installer displays a warning and the link can be added manually.

The Advisor web interface is installed at:

    /var/www/html/winlink-advisor.php

The page automatically reads the station callsign from:

    /home/pi/localize.env

The callsign is therefore specific to the DigiPi on which the Advisor is installed. It is not stored in the GitHub package.

## WSPR Data

The Advisor uses recent WSPR reception reports.

The default freshness window is approximately **30 minutes**. If no suitable WSPR reports have been received recently, the Advisor may correctly show that there is no fresh propagation data.

This is intentional.

Running WSPR and allowing reports to reach the WSPR/PSKReporter systems provides the propagation observations used by the Advisor.

## HF Bands

The Advisor supports:

- 160m
- 80m
- 40m
- 30m
- 20m
- 17m
- 15m
- 12m
- 10m

The interface can use automatic band selection or a specific band.

## Propagation Regions

North American stations are grouped into three broad regions:

- **West**
- **Central**
- **East**

The boundaries are based primarily on longitude and are inspired by broad North American time-zone geography rather than exact political or time-zone boundaries.

European and African areas are represented separately as:

- **Europe / Atlantic**
- **Europe / Africa**

These regions are intended to provide useful propagation groupings rather than precise geographic boundaries.

## Scoring

The Advisor considers factors including:

- Number of unique WSPR receivers
- Signal strength
- Report freshness
- Geographic distribution of receivers
- Available Winlink gateway information

Fresh propagation observations receive more weight than older observations.

WSPR reception is treated as propagation evidence. It does not guarantee that a particular Winlink connection will succeed.

## Winlink Gateway Information

The Advisor retrieves public Winlink HF gateway channel information even
when `WINLINK_KEY` is not configured. If a personal key is configured, the
existing authenticated lookup is retained.

The Advisor considers VARA and ARDOP channels and combines gateway information
with WSPR propagation observations to produce recommendations. WSPR data is
still required for propagation-based recommendations, and gateway status or
API availability can affect the results.

## ARDOP + PAT Controls

The dashboard provides two controls:

- **Start ARDOP + PAT** asks DigiPi to start the existing `ardop.service` and `pat.service`, then reports whether both services became active.
- **Open PAT Email** opens the existing PAT web interface in a new browser window or tab at port 8080.

Starting the services does not select a gateway or connect to a Winlink station. Select the gateway and initiate the connection manually in PAT.

The start button requires PAT and ARDOP to be installed and configured on DigiPi. If startup fails, the dashboard can show diagnostic output. The button does not install or configure the radio stack, and the installer does not start either service.

A DigiPi without PAT or ARDOP can still use the propagation Advisor, but the corresponding controls will not be functional until those services are installed and configured.

## Updating

### Routine updates

Once the updater is present in your repository, run it as the normal
DigiPi user (`pi`), without `sudo`:

    cd /home/pi/winlink-advisor
    ./update.sh

The updater performs the following steps:

1. Checks the repository and confirms the expected GitHub remote.
2. Checks for local changes to tracked files.
3. Remounts the DigiPi filesystem for writing.
4. Creates timestamped backups of the repository and installed files.
5. Fetches the latest version from the project's GitHub `main` branch.
6. Updates the repository and runs the installer.
7. Verifies the installed files and Python syntax.

Wait for the message `UPDATE COMPLETED SUCCESSFULLY` before treating
the update as successful. If the updater reports an error, read the
message carefully and retain the backups before attempting recovery.

Do not run the updater with `sudo`. It requests elevated permissions
for the operations that need them.

### Updating an older installation for the first time

Older repository copies may not contain `update.sh`. Back up the
existing repository before retrieving the newer version.

Run the following block as user `pi`. It stops if any command fails:

    set -e
    cd /home/pi/winlink-advisor
    sudo remount
    tar -czf "/home/pi/winlink-advisor-before-update-$(date +%Y%m%d-%H%M%S).tar.gz" -C /home/pi winlink-advisor
    git fetch origin
    git reset --hard origin/main
    ./update.sh

Do not proceed with the update if creating the backup fails. If the
Git fetch fails, resolve the network or Git problem before retrying.

The archive is created before Git replaces tracked repository files.
Keep it until the updated installation has been tested.

**Warning:** `git reset --hard origin/main` discards local changes to
tracked files. The archive above preserves a copy of the repository
before that operation. If the backup or Git update fails, stop and
resolve the problem before proceeding.

These instructions assume the existing repository uses the official
project remote and the standard path `/home/pi/winlink-advisor`.

## Backups and recovery

The installer and updater create backups in different locations.

Installer backups:

    /home/pi/winlink-advisor/backups/

Updater backups:

    /home/pi/winlink-advisor-update-backups/

The updater's timestamped backup directory contains:

- `repository.tar.gz` — a copy of the repository files, excluding Git
  internals and previous repository backups.
- `installed-files.tar.gz` — copies of the existing Advisor engine,
  web interface, help file, dashboard background image, and DigiPi home
  page when those files exist.

The first-update procedure for older installations also creates a
timestamped archive under `/home/pi/`.

Keep the backups until you have verified the updated web interface
and tested the features you rely on. Successful installation does not
guarantee that fresh PSK Reporter data is available.

The updater does not intentionally modify `/home/pi/localize.env` or
configure PAT, Mercury, VARA, ARDOP, or the radio.

## Troubleshooting

### No fresh WSPR data

If the Advisor reports no fresh data:

1. Check that WSPR is running.
2. Check that your station is transmitting.
3. Allow reports to reach the WSPR/PSKReporter systems.
4. Check the selected band.
5. Remember that the Advisor uses a limited freshness window.

No fresh data does not necessarily indicate a software problem.

### Winlink gateway information unavailable

`WINLINK_KEY` is optional. Without it, the Advisor attempts to retrieve
public Winlink gateway channel information using its public access mechanism.
A personal key is not required for this fallback.

If gateway retrieval fails, inspect the advisor output for the reported
API error. Keep any personal credentials out of the GitHub repository.

### PAT email interface unavailable

The **Open PAT Email** button opens the existing PAT web interface. Confirm that PAT is installed and running and that its web interface is reachable. If needed, use **Start ARDOP + PAT** on the dashboard to request startup of the existing services, then retry the PAT link.

The start button does not select a gateway or initiate a Winlink connection; do that manually in PAT.

### PHP syntax check

The installed PHP file can be checked with:

    php -l /var/www/html/winlink-advisor.php

### Python syntax check

The installed Advisor engine can be checked with:

    python3 -m py_compile /home/pi/winlink-advisor/advisor.py

## Files Installed

The installer places:

    /home/pi/winlink-advisor/advisor.py

and:

    /var/www/html/winlink-advisor.php
    /var/www/html/winlink-advisor-help.txt
    /var/www/html/winlink-advisor-assets/misty-mountain-sunset.png

Backups are stored beneath:

    /home/pi/winlink-advisor/backups/

## Security and Configuration

Do not commit `/home/pi/localize.env` to GitHub.

The repository `.gitignore` excludes local environment/configuration files and runtime artifacts.

In particular, do not publish:

    WINLINK_KEY

The installer only reports whether the key is present.

## Project Status

Version 2.0.0 introduces a redesigned dashboard while retaining the Advisor's WSPR-based propagation analysis and Winlink gateway information.

Highlights include:

- Mountain-sunset dashboard background and refreshed visual layout
- Callsign and grid square displayed in the header
- Gateway recommendation cards with Top 5, 10, 15, or 20 selection
- Regional recommendations filtered to match the selected limit
- Open PAT Email link to the existing PAT web interface
- Installer support for deploying and backing up the dashboard image
- Updater backups that include the installed dashboard image

The Advisor continues to leave the existing radio stack under the operator's control.

## Author

Created by **Peter Busha — WA1PB** for amateur-radio experimentation, education, and practical DigiPi use.

## License

Copyright 2026 Peter Busha.

This project is licensed under the MIT License. See `LICENSE` for the full license text.
