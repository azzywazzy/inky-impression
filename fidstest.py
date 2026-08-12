#!/usr/bin/env python3
"""Dump the raw AeroDataBox FIDS response for your airport.

    python fidstest.py                  # next 12 hours, from 2 hours ago
    python fidstest.py --hours 4
    python fidstest.py --icao EGCC

The point of this is to see the real field names before any parser gets
written against them. Send me the output and I'll build the join.

The key is read from, in order: config.AERODATABOX_KEY, the AERODATABOX_KEY
environment variable, or --key on the command line. It is never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests

HOST = "aerodatabox.p.rapidapi.com"
ENDPOINT = "https://" + HOST + "/flights/airports/icao/{icao}"


def find_key(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("AERODATABOX_KEY"):
        return os.environ["AERODATABOX_KEY"]
    try:
        import config
        key = getattr(config, "AERODATABOX_KEY", "")
        if key and key != "PUT_YOUR_KEY_HERE":
            return key
    except Exception:  # noqa: BLE001 - config is optional for this script
        pass
    sys.exit("No API key. Add AERODATABOX_KEY to config.py, set the "
             "environment variable, or pass --key.")


def find_icao(explicit: str | None) -> str:
    if explicit:
        return explicit.upper()
    try:
        import config
        return getattr(config, "HOME_AIRPORT_ICAO", "EGNM").upper()
    except Exception:  # noqa: BLE001
        return "EGNM"


def describe(node, indent=0, path=""):
    """Print the shape of a nested structure without dumping every value."""
    pad = "  " * indent
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}:")
                describe(v, indent + 1, f"{path}.{k}")
            else:
                print(f"{pad}{k} = {v!r}")
    elif isinstance(node, list):
        print(f"{pad}[{len(node)} items]")
        if node:
            describe(node[0], indent + 1, path + "[0]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--icao")
    ap.add_argument("--key")
    ap.add_argument("--offset", type=int, default=-120,
                    help="minutes relative to now to start (default -120)")
    ap.add_argument("--hours", type=int, default=12,
                    help="window length in hours (default 12)")
    args = ap.parse_args()

    key = find_key(args.key)
    icao = find_icao(args.icao)
    url = ENDPOINT.format(icao=icao)
    params = {"offsetMinutes": args.offset,
              "durationMinutes": args.hours * 60}

    print(f"GET {url}")
    print(f"    {params}")
    print(f"    key: ...{key[-4:]} (masked)\n")

    try:
        r = requests.get(url, params=params, timeout=30, headers={
            "X-RapidAPI-Key": key,
            "X-RapidAPI-Host": HOST,
            "Accept": "application/json",
        })
    except Exception as exc:  # noqa: BLE001
        print(f"REQUEST FAILED: {type(exc).__name__}: {exc}")
        return 1

    print(f"HTTP {r.status_code}  ({len(r.content)} bytes)")
    for h in ("x-ratelimit-requests-remaining", "x-ratelimit-requests-limit",
              "x-ratelimit-rapid-free-plans-hard-limit-remaining"):
        if h in r.headers:
            print(f"  {h}: {r.headers[h]}")
    print()

    if r.status_code == 401 or r.status_code == 403:
        print("Key rejected. Check you've subscribed to AeroDataBox on "
              "RapidAPI (subscribing is separate from having an account).")
        print("body:", r.text[:300])
        return 1
    if r.status_code == 429:
        print("Quota exhausted for this period.")
        return 1
    if r.status_code >= 400:
        print("body:", r.text[:500])
        return 1

    try:
        data = r.json()
    except ValueError:
        print("Not JSON. First 500 chars:\n", r.text[:500])
        return 1

    print("=" * 62)
    print("TOP-LEVEL SHAPE")
    print("=" * 62)
    if isinstance(data, dict):
        for k, v in data.items():
            kind = type(v).__name__
            size = f" [{len(v)} items]" if isinstance(v, list) else ""
            print(f"  {k}: {kind}{size}")
    else:
        print(f"  (top level is a {type(data).__name__})")

    for section in ("departures", "arrivals"):
        flights = data.get(section, []) if isinstance(data, dict) else []
        if not flights:
            continue
        print()
        print("=" * 62)
        print(f"{section.upper()}: {len(flights)} flights")
        print("=" * 62)
        print("\n--- first entry, full structure ---")
        describe(flights[0], 1)

        print("\n--- raw JSON of first entry ---")
        print(json.dumps(flights[0], indent=2)[:1200])

        # The thing that decides whether this whole approach works.
        with_reg = sum(1 for f in flights
                       if isinstance(f.get("aircraft"), dict)
                       and f["aircraft"].get("reg"))
        print(f"\n--- JOIN FEASIBILITY ---")
        print(f"  {with_reg}/{len(flights)} entries carry an aircraft "
              f"registration")
        if with_reg:
            print("  sample registrations:", ", ".join(
                f["aircraft"]["reg"] for f in flights[:8]
                if isinstance(f.get("aircraft"), dict)
                and f["aircraft"].get("reg")))
        else:
            print("  none - we'd have to join on flight number instead, "
                  "which is weaker.")

        print("\n--- SUMMARY OF FIRST 8 ---")
        for f in flights[:8]:
            num = f.get("number", "?")
            mv = f.get("movement") or {}
            apt = (mv.get("airport") or {})
            place = apt.get("name") or apt.get("iata") or "?"
            when = (mv.get("scheduledTime") or {})
            local = when.get("local", "?") if isinstance(when, dict) else when
            reg = (f.get("aircraft") or {}).get("reg", "-")
            print(f"  {num:10} {place[:24]:24} {str(local)[:16]:16} {reg}")

    print("\nDone. Send me everything above (the key is masked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
