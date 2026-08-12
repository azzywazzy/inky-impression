#!/usr/bin/env python3
"""Diagnose the route lookup in isolation.

    python routetest.py                 # use callsigns actually overhead now
    python routetest.py EXS811 RYR7664  # or test specific ones

Prints the raw response before any parsing, so we can tell apart "the service
doesn't know this callsign", "the response shape changed", and "the request
didn't work at all".
"""

from __future__ import annotations

import json
import sys
import time

import requests

import config
from inkyapps.routes import ENDPOINT, USER_AGENT, _parse

AIRCRAFT = "https://api.airplanes.live/v2/point/{lat}/{lon}/{radius}"


def live_callsigns():
    url = AIRCRAFT.format(lat=config.LATITUDE, lon=config.LONGITUDE,
                          radius=config.SEARCH_RADIUS_NM)
    print(f"Fetching aircraft near {config.LATITUDE}, {config.LONGITUDE} "
          f"({config.SEARCH_RADIUS_NM} nm)...")
    r = requests.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    ac = r.json().get("ac", []) or []
    print(f"  {len(ac)} aircraft in range")
    seen = []
    for a in ac:
        cs = (a.get("flight") or "").strip()
        if cs and cs not in seen:
            seen.append(cs)
    return seen[:6]


def main(argv) -> int:
    callsigns = [c.upper() for c in argv[1:]]
    if not callsigns:
        try:
            callsigns = live_callsigns()
        except Exception as exc:  # noqa: BLE001
            print(f"  couldn't reach airplanes.live: {exc}")
            return 1
        if not callsigns:
            print("  nothing with a callsign right now - pass some by hand:\n"
                  "    python routetest.py EXS811")
            return 1

    print(f"\nLooking up {len(callsigns)} callsign(s) at {ENDPOINT}\n")
    resolved = unknown = failed = 0

    for i, cs in enumerate(callsigns):
        if i:
            time.sleep(0.3)
        url = ENDPOINT.format(callsign=cs)
        try:
            r = requests.get(url, timeout=15, headers={
                "Accept": "application/json", "User-Agent": USER_AGENT})
        except Exception as exc:  # noqa: BLE001
            print(f"{cs:10} REQUEST FAILED: {type(exc).__name__}: {exc}")
            failed += 1
            continue

        if r.status_code == 404:
            print(f"{cs:10} 404 - adsbdb doesn't know this callsign")
            unknown += 1
            continue
        if r.status_code >= 400:
            print(f"{cs:10} HTTP {r.status_code}: {r.text[:120]}")
            failed += 1
            continue

        try:
            payload = r.json()
        except ValueError:
            print(f"{cs:10} HTTP {r.status_code}, {len(r.content)} bytes, "
                  f"not JSON: {r.text[:120]!r}")
            failed += 1
            continue

        route = _parse(payload)
        if route:
            away = route.away_end(config.HOME_AIRPORT_IATA)
            extra = f"  ({away[0]} {away[1]})" if away else ""
            print(f"{cs:10} {route.short():14} {route.long()}{extra}")
            if route.airline:
                print(f"{'':10} operator: {route.airline}")
            resolved += 1
        else:
            print(f"{cs:10} HTTP 200 but no route in the body:")
            print("           " + json.dumps(payload)[:220])
            unknown += 1

    print(f"\n{resolved} resolved, {unknown} unknown, {failed} failed.")
    if failed:
        print("\nFailures mean a network or service problem - send me the "
              "output above.")
    elif not resolved:
        print("\nEverything came back unknown. That's normal for private "
              "aircraft and some\ncharter callsigns; try again when a "
              "scheduled airliner is overhead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
