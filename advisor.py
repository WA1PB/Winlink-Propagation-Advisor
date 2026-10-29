#!/usr/bin/env python3
"""
Winlink Propagation Advisor

Uses the operator's own WSPR beacon spots (via PSKReporter) as live
propagation evidence, then cross-references that evidence against
current Winlink VARA/ARDOP gateway status to recommend the best
gateway to try right now.
"""

import argparse
import json
import math
import os
import re
import statistics
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

CONFIG_PATH = "/home/pi/localize.env"
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "score_log.jsonl")

FRESHNESS_LIMIT_MINUTES = 30
WSPR_ANALYSIS_HOURS = 24
GATEWAY_EVIDENCE_RADIUS_KM = 1500
WINLINK_HISTORY_HOURS = 36

BANDS = [
    (1800000, 2000000, "160m"),
    (3500000, 4000000, "80m"),
    (7000000, 7300000, "40m"),
    (10100000, 10150000, "30m"),
    (14000000, 14350000, "20m"),
    (18068000, 18168000, "17m"),
    (21000000, 21450000, "15m"),
    (24890000, 24990000, "12m"),
    (28000000, 29700000, "10m"),
]

VALID_BAND_NAMES = {b[2] for b in BANDS}


def load_config(path):
    """Load station settings and the optional WINLINK_KEY.

    A callsign and grid are required. The API key is optional and is
    only needed for Winlink gateway-status information.
    """
    config = {"NEWCALL": "", "NEWGRID": "", "WINLINK_KEY": ""}

    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key in config:
                    config[key] = value.strip()
    except FileNotFoundError:
        print(f"ERROR: config file not found: {path}")
        sys.exit(1)

    if not config["NEWCALL"] or not config["NEWGRID"]:
        print(f"ERROR: NEWCALL and NEWGRID must be set in {path}")
        sys.exit(1)

    if not config["WINLINK_KEY"]:
        print(
            "INFO: WINLINK_KEY is not set in "
            f"{path}. Public Winlink gateway access will be used."
        )

    return config["NEWCALL"], config["NEWGRID"], config["WINLINK_KEY"]


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def get_band(frequency_hz):
    for low, high, band in BANDS:
        if low <= frequency_hz <= high:
            return band
    return "Unknown"


def get_tag(record, tag):
    pattern = rf"<{tag}:\d+(?::[A-Za-z])?>([^<]*)"
    match = re.search(pattern, record, re.IGNORECASE)
    return match.group(1).strip() if match else None


def grid_to_latlon(grid):
    """Convert a 4- or 6-character Maidenhead grid square to lat/lon.

    4-character grids (the common case for WSPR spotters that haven't
    enabled extended precision) resolve to the center of that square
    instead of raising and being silently dropped.
    """
    grid = grid.strip().upper()

    if len(grid) < 4:
        raise ValueError(f"grid square too short: {grid!r}")

    lon = (ord(grid[0]) - ord("A")) * 20 - 180
    lat = (ord(grid[1]) - ord("A")) * 10 - 90
    lon += int(grid[2]) * 2
    lat += int(grid[3])

    if len(grid) >= 6 and grid[4].isalpha() and grid[5].isalpha():
        lon += (ord(grid[4]) - ord("A")) * (5 / 60) + 5 / 120
        lat += (ord(grid[5]) - ord("A")) * (2.5 / 60) + 2.5 / 120
    else:
        # Center of the 4-character square (2 deg lon x 1 deg lat).
        lon += 1.0
        lat += 0.5

    return lat, lon


def distance_bearing(grid1, grid2):
    lat1, lon1 = map(math.radians, grid_to_latlon(grid1))
    lat2, lon2 = map(math.radians, grid_to_latlon(grid2))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance_km = 6371.0 * c

    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360

    return distance_km, bearing


def classify_region(lat, lon):
    # North America: broad propagation regions based on longitude.
    # These are approximate bands inspired by North American time zones,
    # not political or exact time-zone boundaries.
    if lon < -110:
        return "West"
    if lon < -90:
        return "Central"
    if lon < -50:
        return "East"

    # Europe / Atlantic and Europe / Africa remain separate.
    if -50 <= lon < 15:
        return "Europe / Atlantic"
    if lon >= 15:
        return "Europe / Africa"

    return "Other"


# --------------------------------------------------------------------------
# WSPR fetch / parse
# --------------------------------------------------------------------------

def fetch_wspr_reports(callsign):
    """Download and parse the operator's WSPR spots from PSKReporter.

    Returns a list of report dicts. Returns an empty list (rather than
    raising) on network/parse failure so callers have one thing to check.
    """
    url = (
        "https://pskreporter.info/cgi-bin/pskdata.pl"
        "?adif=1&days=2&senderCallsign=" + callsign + "&mode=WSPR"
    )

    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read().decode("utf-8", errors="replace")

    records = re.split(r"<eor>", data, flags=re.IGNORECASE)
    reports = []

    for record in records:
        frequency = get_tag(record, "FREQ")
        receiver = get_tag(record, "OPERATOR")
        receiver_grid = get_tag(record, "MY_GRIDSQUARE")
        qso_date = get_tag(record, "QSO_DATE")
        time_on = get_tag(record, "TIME_ON")
        snr = get_tag(record, "APP_PSKREP_SNR")

        if not all([frequency, receiver, qso_date, time_on]):
            continue

        try:
            frequency_hz = float(frequency) * 1000000
            timestamp = datetime.strptime(
                qso_date + time_on, "%Y%m%d%H%M%S"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        try:
            snr_value = float(snr)
        except (TypeError, ValueError):
            snr_value = None

        reports.append({
            "frequency": frequency_hz,
            "band": get_band(frequency_hz),
            "receiver": receiver,
            "receiver_grid": receiver_grid or "",
            "snr": snr_value,
            "timestamp": timestamp,
        })

    return reports


def group_by_band(reports):
    bands = {}
    for report in reports:
        bands.setdefault(report["band"], []).append(report)
    return bands


def print_band_status(bands, now):
    print()
    print("Reports by band:")
    for band, band_reports in sorted(bands.items()):
        receivers = len(set(r["receiver"] for r in band_reports))
        print(f"  {band:6s}  {len(band_reports):3d} reports  {receivers:3d} receivers")

    print()
    print("CURRENT WSPR BAND STATUS")
    print("=========================")

    fresh_bands = []
    for band, band_reports in sorted(bands.items()):
        band_newest = max(r["timestamp"] for r in band_reports)
        band_age = (now - band_newest).total_seconds() / 60
        receivers = len(set(r["receiver"] for r in band_reports))

        if band_age <= FRESHNESS_LIMIT_MINUTES:
            status = "FRESH"
            fresh_bands.append(band)
        else:
            status = "aging"

        print(
            f"  {band:6s} reports={len(band_reports):3d} receivers={receivers:3d} "
            f"age={band_age:6.1f} min {status}"
        )

    return fresh_bands


def detect_active_band(bands, fresh_bands, now):
    print()

    candidate_bands = fresh_bands if fresh_bands else list(bands.keys())
    label = "Detected active" if fresh_bands else "Fallback"

    if fresh_bands:
        print("Fresh WSPR bands: " + ", ".join(fresh_bands))
    else:
        print("No WSPR bands currently have fresh data.")

    detected_band = max(
        candidate_bands,
        key=lambda b: max(r["timestamp"] for r in bands[b])
    )
    detected_newest = max(r["timestamp"] for r in bands[detected_band])
    detected_age = (now - detected_newest).total_seconds() / 60

    print(f"{label} WSPR band: {detected_band}")
    print(f"{label} band newest report: {detected_newest.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{label} band age: {detected_age:.1f} minutes")

    return detected_band


# --------------------------------------------------------------------------
# Propagation scoring
# --------------------------------------------------------------------------

def wspr_age_weight(timestamp, now):
    age_minutes = (now - timestamp).total_seconds() / 60
    if age_minutes <= 30:
        return 1.00
    if age_minutes <= 60:
        return 0.85
    if age_minutes <= 120:
        return 0.65
    if age_minutes <= 360:
        return 0.40
    if age_minutes <= 720:
        return 0.20
    return 0.05


def build_wspr_evidence(reports, now):
    """Use the most recent report per (band, receiver) pair.

    If reports have the same timestamp, prefer the stronger SNR.
    Freshness is applied separately when scoring gateway evidence.
    """
    cutoff = now - timedelta(hours=WSPR_ANALYSIS_HOURS)

    recent = [
        r for r in reports
        if r["band"] != "Unknown"
        and r["timestamp"] >= cutoff
        and r["receiver_grid"]
        and r["snr"] is not None
    ]

    best_by_receiver_band = {}
    for r in recent:
        r["age_weight"] = wspr_age_weight(r["timestamp"], now)
        key = (r["band"], r["receiver"])
        current = best_by_receiver_band.get(key)

        if (
            current is None
            or r["timestamp"] > current["timestamp"]
            or (
                r["timestamp"] == current["timestamp"]
                and r["snr"] > current["snr"]
            )
        ):
            best_by_receiver_band[key] = r

    return recent, list(best_by_receiver_band.values())


def compute_band_populations(recent_wspr):
    """Count distinct receivers per band within the analysis window.

    This is a proxy for how many WSPR stations are actively monitoring
    each band right now. Busier bands (typically 20m/40m) will otherwise
    generate bigger evidence counts by default, which would make the
    score reflect "how popular is this band with WSPR operators" rather
    than "how good is propagation to this specific gateway." Used to
    scale each gateway's receiver count relative to a typical band.
    """
    receivers_by_band = {}
    for r in recent_wspr:
        receivers_by_band.setdefault(r["band"], set()).add(r["receiver"])

    populations = {band: len(receivers) for band, receivers in receivers_by_band.items()}
    reference_population = statistics.median(populations.values()) if populations else 1
    return populations, max(1, reference_population)


def gateway_wspr_evidence(gateway_grid, gateway_band, wspr_evidence):
    evidence = []
    for r in wspr_evidence:
        if r["band"] != gateway_band:
            continue
        try:
            distance_km, bearing = distance_bearing(gateway_grid, r["receiver_grid"])
        except Exception:
            continue
        if distance_km <= GATEWAY_EVIDENCE_RADIUS_KM:
            evidence.append((r, distance_km, bearing))
    return evidence


def score_gateway_propagation(
    gateway_grid, gateway_band, wspr_evidence, station_grid,
    band_populations=None, reference_population=1,
):
    evidence = gateway_wspr_evidence(gateway_grid, gateway_band, wspr_evidence)

    try:
        station_to_gateway_km, station_to_gateway_bearing = distance_bearing(
            station_grid, gateway_grid
        )
    except Exception:
        station_to_gateway_km = None
        station_to_gateway_bearing = None

    empty_result = {
        "score": 0,
        "receivers": 0,
        "station_to_gateway_km": station_to_gateway_km,
        "station_to_gateway_bearing": station_to_gateway_bearing,
        "best_snr": None,
        "avg_snr": None,
        "median_snr": None,
        "within_500": 0,
        "within_1000": 0,
        "within_1500": 0,
        "good": 0,
        "marginal": 0,
        "weak": 0,
    }

    if not evidence:
        return empty_result

    snrs = [r["snr"] for r, _, _ in evidence]
    distances = [d for _, d, _ in evidence]

    good = marginal = weak = 0
    usable = 0.0

    for r, _, _ in evidence:
        s = r["snr"]
        age = r["age_weight"]
        if s >= -10:
            good += 1
            usable += 1.0 * age
        elif s >= -15:
            marginal += 1
            usable += 0.20 * age
        else:
            weak += 1

    rx = len(evidence)

    # Effective receiver count for confidence purposes excludes weak
    # (< -15 dB) reports: a receiver that barely heard you is not real
    # evidence that the path supports a Winlink session, and shouldn't
    # earn the same confidence credit as a good/marginal one.
    effective_rx = good + marginal

    # Normalize the effective receiver count against how many WSPR
    # stations are monitoring this band overall, relative to a typical
    # band. Without this, busier bands (e.g. 20m/40m) systematically
    # outscore quieter-but-open bands purely because more people are
    # listening, not because propagation is actually better.
    band_population = (band_populations or {}).get(gateway_band, reference_population)
    normalized_rx = effective_rx * (reference_population / max(1, band_population))

    # Single consolidated receiver-count term. Previously this signal
    # was applied three times (as a multiplier, an additive bonus, and
    # implicitly via the raw evidence count in `usable`), which made the
    # score's sensitivity to receiver count hard to reason about and let
    # it swamp the signal-quality terms below at high receiver counts.
    receiver_confidence = min(1.5, 0.55 + math.log2(normalized_rx + 1) / 3.0)

    sorted_snrs = sorted(snrs)
    mid = len(sorted_snrs) // 2
    if len(sorted_snrs) % 2:
        median_snr = sorted_snrs[mid]
    else:
        median_snr = (sorted_snrs[mid - 1] + sorted_snrs[mid]) / 2

    avg_snr = sum(snrs) / len(snrs)
    best_snr = max(snrs)

    within_500 = sum(1 for d in distances if d <= 500)
    within_1000 = sum(1 for d in distances if d <= 1000)
    within_1500 = sum(1 for d in distances if d <= 1500)

    # Median SNR is more informative than one unusually strong report.
    median_bonus = max(0.0, min(3.0, (median_snr + 20.0) / 10.0))
    # Rewards gateways with at least one strong path.
    best_bonus = max(0.0, min(2.0, (best_snr + 15.0) / 10.0))
    # Favors evidence geographically close to the gateway.
    distance_bonus = min(2.5, within_500 * 0.35 + within_1000 * 0.15 + within_1500 * 0.05)

    total_score = (
        usable * receiver_confidence
        + median_bonus
        + best_bonus
        + distance_bonus
    )

    return {
        "score": total_score,
        "receivers": rx,
        "station_to_gateway_km": station_to_gateway_km,
        "station_to_gateway_bearing": station_to_gateway_bearing,
        "best_snr": best_snr,
        "avg_snr": avg_snr,
        "median_snr": median_snr,
        "within_500": within_500,
        "within_1000": within_1000,
        "within_1500": within_1500,
        "good": good,
        "marginal": marginal,
        "weak": weak,
    }


def print_regional_breakdown(wspr_evidence, now):
    regions = {}
    for r in wspr_evidence:
        try:
            lat, lon = grid_to_latlon(r["receiver_grid"])
        except Exception:
            continue
        region = classify_region(lat, lon)
        regions.setdefault(region, []).append(r)

    print()
    for region, receivers in sorted(regions.items(), key=lambda item: (-len(item[1]), item[0])):
        snrs = [r["snr"] for r in receivers]
        fresh = sum(
            1 for r in receivers
            if (now - r["timestamp"]).total_seconds() <= FRESHNESS_LIMIT_MINUTES * 60
        )
        print(
            f"{region:24s} receivers={len(receivers):2d} fresh={fresh:2d} "
            f"best={max(snrs):+4.1f} avg={sum(snrs) / len(snrs):+5.1f}"
        )


# --------------------------------------------------------------------------
# Winlink gateway fetch
# --------------------------------------------------------------------------

def _fetch_winlink_channels_with_key(winlink_key):
    winlink_channels = []

    for winlink_mode in ["VARA", "ARDOP"]:
        url = (
            "https://cms.winlink.org/gateway/status?"
            f"historyHours={WINLINK_HISTORY_HOURS}&mode={winlink_mode}"
            f"&serviceCodes=PUBLIC&format=json&key={winlink_key}"
        )

        try:
            with urllib.request.urlopen(url, timeout=15) as response:
                data = json.load(response)

            records = []
            for gw in data.get("Gateways", []):
                for ch in gw.get("GatewayChannels", []):
                    freq = ch.get("Frequency", 0)
                    band = get_band(freq)
                    if band == "Unknown":
                        continue
                    record = {
                        "callsign": gw.get("Callsign", ""),
                        "grid": ch.get("Gridsquare", ""),
                        "frequency": freq,
                        "band": band,
                        "mode": ch.get("SupportedModes", ""),
                        "hours": ch.get("OperatingHours", ""),
                        "status_hours": gw.get("HoursSinceStatus", 99),
                    }
                    records.append(record)
                    winlink_channels.append(record)

            print(f"{winlink_mode}: {len(records)} HF channels (160m-10m)")
            for g in records[:10]:
                print(
                    f"{g['callsign']:8s} {g['grid']:6s} "
                    f"{g['frequency'] / 1000000:.4f} MHz {g['band']:5s} "
                    f"{g['mode']:12s} {g['hours']}"
                )

        except Exception as e:
            print(f"{winlink_mode} ERROR: {e}")

    return winlink_channels

def fetch_winlink_channels(winlink_key):
    """Retrieve HF gateway channels using a personal or public API key.

    Preserve the existing personal-key endpoint when a key is configured.
    Otherwise use the public access mechanism used by PAT.
    """
    if winlink_key:
        return _fetch_winlink_channels_with_key(winlink_key)

    public_key = "1880278F11684B358F36845615BD039A"
    url = "https://api.winlink.org/gateway/status.json"
    params = urllib.parse.urlencode({
        "historyHours": WINLINK_HISTORY_HOURS,
        "mode": "allhf",
        "serviceCodes": "PUBLIC",
        "key": public_key,
    })
    request = urllib.request.Request(
        url + "?" + params,
        headers={"User-Agent": "Winlink-Propagation-Advisor/1.0"},
    )

    winlink_channels = []

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)

        counts = {"VARA": 0, "ARDOP": 0}

        for gw in data.get("Gateways", []):
            for ch in gw.get("GatewayChannels", []):
                supported = str(ch.get("SupportedModes", ""))
                supported_upper = supported.upper()

                if "VARA" not in supported_upper and "ARDOP" not in supported_upper:
                    continue

                freq = ch.get("Frequency", 0)
                band = get_band(freq)

                if band == "Unknown":
                    continue

                record = {
                    "callsign": gw.get("Callsign", ""),
                    "grid": ch.get("Gridsquare", ""),
                    "frequency": freq,
                    "band": band,
                    "mode": supported,
                    "hours": ch.get("OperatingHours", ""),
                    "status_hours": gw.get("HoursSinceStatus", 99),
                }

                winlink_channels.append(record)

                if "VARA" in supported_upper:
                    counts["VARA"] += 1
                if "ARDOP" in supported_upper:
                    counts["ARDOP"] += 1

        print("Public Winlink gateway API:")
        print(f"VARA:  {counts['VARA']} HF channels")
        print(f"ARDOP: {counts['ARDOP']} HF channels")
        print(f"Total eligible channel records: {len(winlink_channels)}")

        for gateway in winlink_channels[:10]:
            print(
                f"{gateway['callsign']:8s} {gateway['grid']:6s} "
                f"{gateway['frequency'] / 1000000:.4f} MHz "
                f"{gateway['band']:5s} {gateway['mode']:12s} "
                f"{gateway['hours']}"
            )

    except Exception as exc:
        print(f"WINLINK API ERROR: Public gateway lookup failed: {exc}")

    return winlink_channels


def resolve_selected_band(detected_band, bands, now):
    """Read WINLINK_ADVISOR_BAND from the environment and validate it.

    Falls back to the auto-detected band (with a warning) instead of
    silently producing an empty result on a typo or bad value.
    """
    raw = os.environ.get("WINLINK_ADVISOR_BAND", "AUTO").upper()

    if raw == "AUTO":
        return "AUTO", detected_band

    normalized = raw if raw.endswith("M") else raw + "M"
    normalized = normalized[:-1] + "m"

    if normalized not in VALID_BAND_NAMES:
        print(
            f"WARNING: WINLINK_ADVISOR_BAND={raw!r} is not a recognized band "
            f"({sorted(VALID_BAND_NAMES)}); falling back to AUTO."
        )
        return "AUTO", detected_band

    if normalized not in bands:
        print(f"WARNING: no WSPR data available for selected band {normalized}.")
        return normalized, None

    return normalized, normalized


def rank_gateways(
    winlink_channels, target_band, winlink_mode, wspr_evidence, station_grid,
    band_populations, reference_population,
):
    ranked = []

    for g in winlink_channels:
        if not g["grid"] or target_band is None or g["band"] != target_band:
            continue

        gateway_mode = g["mode"].upper()
        if winlink_mode != "BOTH" and winlink_mode not in gateway_mode:
            continue

        score = score_gateway_propagation(
            g["grid"], g["band"], wspr_evidence, station_grid,
            band_populations, reference_population,
        )

        try:
            lat, lon = grid_to_latlon(g["grid"])
            g["region"] = classify_region(lat, lon)
        except (ValueError, TypeError):
            g["region"] = "Other"

        if score["receivers"] > 0:
            ranked.append((score["score"], g, score))

    # Keep only the highest-scoring channel per gateway callsign/grid.
    best_by_gateway = {}
    for item in ranked:
        score_value, g, score = item
        key = (g["callsign"].upper(), g["grid"].upper())
        if key not in best_by_gateway or score_value > best_by_gateway[key][0]:
            best_by_gateway[key] = item

    ranked = list(best_by_gateway.values())
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def print_gateway_directory(channels, winlink_mode="BOTH"):
    """Display published gateway channels without implying propagation."""
    print("PUBLIC WINLINK GATEWAY DIRECTORY")
    print("===============================")
    print("These are published gateway channels, not propagation recommendations.")
    print("Current reachability and operating status are not guaranteed.")

    mode_filter = winlink_mode.upper()
    eligible = []

    for channel in channels:
        supported = str(channel.get("mode", "")).upper()
        if mode_filter != "BOTH" and not (
            supported == mode_filter or supported.startswith(mode_filter + " ")
        ):
            continue
        if not channel.get("frequency") or not channel.get("band"):
            continue
        eligible.append(channel)

    if not eligible:
        print(f"No gateway channels found for mode filter: {mode_filter}")
        return

    eligible.sort(
        key=lambda channel: (
            str(channel.get("band", "")),
            float(channel.get("frequency", 0)),
            str(channel.get("callsign", "")),
        )
    )

    print(f"Mode filter: {mode_filter}")
    print(f"Published channels listed: {len(eligible)}")
    print()
    print(f"{'CALLSIGN':8s} {'GRID':6s} {'FREQUENCY':13s} {'BAND':5s} {'MODE':12s} HOURS")
    print("-" * 67)

    for channel in eligible:
        frequency = float(channel["frequency"]) / 1000000
        print(
            f"{str(channel.get('callsign', '')):8.8s} "
            f"{str(channel.get('grid', '')):6.6s} "
            f"{frequency:8.4f} MHz  "
            f"{str(channel.get('band', '')):5.5s} "
            f"{str(channel.get('mode', '')):12.12s} "
            f"{str(channel.get('hours', ''))}"
        )


def print_rankings(ranked, limit=10):
    print("TOP WINLINK PROPAGATION MATCHES")
    print("===============================")

    if not ranked:
        print("No gateways matched the current band/mode filters.")
        return

    for rank, (score_value, g, score) in enumerate(ranked[:limit], 1):
        km = score["station_to_gateway_km"]
        bearing = score["station_to_gateway_bearing"]
        km_str = f"{km:.0f} km" if km is not None else "unknown distance"
        bearing_str = f"{bearing:.0f}°" if bearing is not None else "unknown bearing"

        print(
            f"{rank:2d}. {g['callsign']:8s} {g['grid']:6s} "
            f"{g['frequency'] / 1000000:.4f} MHz {g['band']:5s} {g['mode']:12s} "
            f"score={score_value:4.1f} rx={score['receivers']:2d} best={score['best_snr']:+.1f}"
        )
        print(
            f"    Why: station→gateway {km_str} ({bearing_str}), "
            f"{score['receivers']} receivers, {score['good']} good (>= -10 dB), "
            f"{score['marginal']} marginal, {score['weak']} weak, "
            f"best {score['best_snr']:+.1f} dB, median {score['median_snr']:+.1f} dB, "
            f"{score['within_500']} within 500 km, {score['within_1000']} within 1000 km"
        )


# --------------------------------------------------------------------------
# Calibration logging
#
# The scoring constants (dB thresholds, distance tiers, bonus caps) are
# hand-tuned heuristics, not fitted to real outcomes. Logging each run's
# top predictions, then later tagging whether the connect actually
# succeeded, builds a dataset that can eventually be used to check (or
# refit) those constants against reality instead of just "feel".
# --------------------------------------------------------------------------

def log_predictions(ranked, band, winlink_mode, now, limit=5):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

    with open(LOG_PATH, "a") as f:
        for score_value, g, score in ranked[:limit]:
            entry = {
                "timestamp": now.isoformat(),
                "band": band,
                "mode": winlink_mode,
                "callsign": g["callsign"],
                "grid": g["grid"],
                "score": round(score_value, 2),
                "receivers": score["receivers"],
                "best_snr": score["best_snr"],
                "median_snr": score["median_snr"],
                "outcome": None,
            }
            f.write(json.dumps(entry) + "\n")


def record_outcome(callsign, outcome):
    """Tag the most recent un-tagged prediction for this callsign with
    a connect outcome ("connected" or "failed"), run via:

        python3 advisor.py outcome <CALLSIGN> connected|failed

    right after you try a session, so the log stays useful.
    """
    if not os.path.exists(LOG_PATH):
        print(f"No log file found at {LOG_PATH}; nothing to record.")
        return

    with open(LOG_PATH) as f:
        entries = [json.loads(line) for line in f if line.strip()]

    target = None
    for entry in reversed(entries):
        if entry["callsign"].upper() == callsign.upper() and entry.get("outcome") is None:
            target = entry
            break

    if target is None:
        print(f"No pending prediction found for {callsign}.")
        return

    target["outcome"] = outcome

    with open(LOG_PATH, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    print(f"Recorded outcome={outcome} for {callsign} (predicted at {target['timestamp']})")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    callsign, station_grid, winlink_key = load_config(CONFIG_PATH)

    print("Winlink Propagation Advisor")
    print("============================")
    print(f"Station callsign: {callsign}")
    print(f"Downloading {callsign} WSPR data...")

    try:
        reports = fetch_wspr_reports(callsign)
    except Exception as e:
        print(f"ERROR: failed to fetch/parse WSPR data: {e}")
        sys.exit(1)

    winlink_mode = os.environ.get("WINLINK_ADVISOR_MODE", "BOTH").upper()

    if not reports:
        print()
        print("WARNING: No usable WSPR reports were returned by PSKReporter.")
        print("Propagation-based gateway rankings will not be available.")
        print("Continuing to retrieve public Winlink gateway information.")

        now = datetime.now(timezone.utc)
        bands = {}
        detected_band = None
        recent_wspr = []
        wspr_evidence = []
        band_populations = {}
        reference_population = 0

    else:
        now = datetime.now(timezone.utc)
        newest = max(r["timestamp"] for r in reports)
        age_minutes = (now - newest).total_seconds() / 60

        print()
        print(f"Total reports:      {len(reports)}")
        print(f"Newest report:      {newest.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Data age:           {age_minutes:.1f} minutes")
        print(f"Freshness limit:    {FRESHNESS_LIMIT_MINUTES} minutes")

        bands = group_by_band(reports)
        fresh_bands = print_band_status(bands, now)
        detected_band = detect_active_band(bands, fresh_bands, now)

        print()
        recent_wspr, wspr_evidence = build_wspr_evidence(reports, now)
        band_populations, reference_population = compute_band_populations(recent_wspr)
        print(f"{BANDS[0][2]}-{BANDS[-1][2]} WSPR analysis window: last {WSPR_ANALYSIS_HOURS} hours")
        print(f"Recent WSPR reports:      {len(recent_wspr)}")
        print(f"Independent receivers:    {len(wspr_evidence)}")

        print_regional_breakdown(wspr_evidence, now)

    print()
    print("WINLINK GATEWAYS — VARA + ARDOP")
    print("================================")

    try:
        winlink_channels = fetch_winlink_channels(winlink_key)
    except Exception as e:
        print(f"WARNING: Winlink gateway lookup failed: {e}")
        winlink_channels = []

    print(f"Winlink mode filter: {winlink_mode}")

    if not reports:
        print()
        print("WSPR evidence is unavailable; skipping propagation ranking.")
        print("No propagation recommendations available until fresh WSPR data is received.")
        return

    print()
    selected_band, target_band = resolve_selected_band(detected_band, bands, now)
    print(f"Selected WSPR band: {selected_band}")
    print(f"Actual WSPR band: {target_band}")

    ranked = rank_gateways(
        winlink_channels, target_band, winlink_mode, wspr_evidence, station_grid,
        band_populations, reference_population,
    )
    print_rankings(ranked, limit=25)

    if ranked:
        log_predictions(ranked, target_band, winlink_mode, now)


def parse_args():
    parser = argparse.ArgumentParser(description="Winlink Propagation Advisor")
    subparsers = parser.add_subparsers(dest="command")

    outcome_parser = subparsers.add_parser(
        "outcome", help="Record whether a connect attempt succeeded"
    )
    outcome_parser.add_argument("callsign", help="Gateway callsign, e.g. W1ABC")
    outcome_parser.add_argument("result", choices=["connected", "failed"])

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.command == "outcome":
        record_outcome(args.callsign, args.result)
    else:
        main()
