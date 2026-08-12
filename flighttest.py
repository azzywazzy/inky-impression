#!/usr/bin/env python3
"""Find AeroDataBox's flight-status endpoint for a single aircraft.

    python flighttest.py 400877 G-EUPG SHT6K
    python flighttest.py            # uses a live aircraft in range

AeroDataBox advertises flight status by Mode-S, registration, callsign and
flight number, but the exact paths aren't clear from the docs. This tries the
plausible ones and reports which works, so the real code can be written
against a verified endpoint instead of a guess.

COSTS QUOTA: up to one request per candidate path. It stops at the first
success, so a lucky first guess costs one request. Worst case is about six.
"""

from __future__ import annotations

import json
import sys
from datetime import date

import requests

import config

HOST = "aerodatabox.p.rapidapi.com"
BASE = "https://" + HOST

AIRCRAFT = "https://api.airplanes.live/v2/point/{lat}/{lon}/{radius}"


def candidates(hexid: str, reg: str, callsign: str, today: str):
    """Paths worth trying, strongest identifier first."""
    out = []
    if hexid:
        out += [f"/flights/icao24/{hexid}",
                f"/flights/icao24/{hexid}/{today}",
                f"/flights/modes/{hexid}"]
    if reg:
        out += [f"/flights/reg/{reg}",
                f"/flights/reg/{reg}/{today}",
                f"/flights/registration/{reg}"]
    if callsign:
        out += [f"/flights/callsign/{callsign}",
                f"/flights/callsign/{callsign}/{today}"]
    return out


def pick_live_aircraft():
    url = AIRCRAFT.format(lat=config.LATITUDE, lon=config.LONGITUDE,
                          radius=config.SEARCH_RADIUS_NM)
    r = requests.get(url, timeout=20,
                     headers={"User-Agent": "inky-apps/1.0 diagnostic"})
    r.raise_for_status()
    for ac in r.json().get("ac", []) or []:
        cs = (ac.get("flight") or "").strip()
        # An airline callsign with a registration is the most useful test case.
        if cs and ac.get("r") and ac.get("hex") and cs[:3].isalpha():
            return ac["hex"], ac["r"], cs
    return "", "", ""


def main(argv) -> int:
    key = getattr(config, "AERODATABOX_KEY", "")
    if not key or key == "PUT_YOUR_KEY_HERE":
        print("AERODATABOX_KEY is not set in config.py")
        return 1

    if len(argv) >= 2:
        hexid = argv[1]
        reg = argv[2] if len(argv) > 2 else ""
        callsign = argv[3] if len(argv) > 3 else ""
    else:
        print("Picking an aircraft in range...")
        hexid, reg, callsign = pick_live_aircraft()
        if not hexid:
            print("  none suitable right now - pass one by hand:\n"
                  "    python flighttest.py 400877 G-EUPG SHT6K")
            return 1

    today = date.today().isoformat()
    print(f"\nTesting hex={hexid} reg={reg} callsign={callsign}\n")

    headers = {"X-RapidAPI-Key": key, "X-RapidAPI-Host": HOST,
               "Accept": "application/json"}

    for path in candidates(hexid, reg, callsign, today):
        url = BASE + path
        try:
            r = requests.get(url, timeout=25, headers=headers)
        except Exception as exc:  # noqa: BLE001
            print(f"  {path:44} REQUEST FAILED: {exc}")
            continue

        remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
        if r.status_code == 404:
            print(f"  {path:44} 404  (quota left {remaining})")
            continue
        if r.status_code >= 400:
            body = r.text[:80].replace("\n", " ")
            print(f"  {path:44} {r.status_code}  {body}")
            continue

        print(f"  {path:44} 200  <- WORKS (quota left {remaining})\n")
        try:
            data = r.json()
        except ValueError:
            print("  response was not JSON:", r.text[:300])
            return 1

        print("=" * 66)
        print("RESPONSE")
        print("=" * 66)
        print(json.dumps(data, indent=2)[:2500])

        # Point out the fields the real code would need.
        record = data[0] if isinstance(data, list) and data else data
        if isinstance(record, dict):
            print("\n--- fields that matter ---")
            for field in ("number", "callSign", "status", "airline",
                          "departure", "arrival", "aircraft", "lastUpdatedUtc"):
                if field in record:
                    value = record[field]
                    if isinstance(value, dict):
                        print(f"  {field}: {sorted(value.keys())}")
                    else:
                        print(f"  {field}: {value!r}")
        print("\nSend me this and I'll wire it in.")
        return 0

    print("\nNone of the candidate paths worked. Send me the output above and "
          "I'll\ncheck the endpoint list on RapidAPI.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
