#!/usr/bin/env python3
"""Why aren't aircraft matching the airport board?

    python fidsmatch.py

Fetches both sides of the join at the same moment - the aircraft currently in
range, and the airport board - then shows exactly which identifiers each side
is offering and which ones line up.

The board only carries a Mode-S hex, registration and callsign for flights
that have gone "Live" (an aircraft assigned). Schedule-only entries have none
of those, so they can never match, and that's expected.
"""

from __future__ import annotations

import sys

import requests

import config
from inkyapps.fids import FidsBoard, _norm_callsign, _norm_hex, _norm_reg

AIRCRAFT = "https://api.airplanes.live/v2/point/{lat}/{lon}/{radius}"
UA = "inky-apps/1.0 diagnostic"


def live_aircraft():
    url = AIRCRAFT.format(lat=config.LATITUDE, lon=config.LONGITUDE,
                          radius=config.SEARCH_RADIUS_NM)
    r = requests.get(url, timeout=20, headers={"User-Agent": UA})
    r.raise_for_status()
    return r.json().get("ac", []) or []


def main() -> int:
    print("Fetching the airport board...")
    board = FidsBoard()
    board.refresh()
    if board.last_error:
        print(f"  board refresh failed: {board.last_error}")
        return 1
    print(f"  {board.entry_count} flights indexed, runway "
          f"{board.runway_in_use or '?'}")
    print(f"  indexed by hex: {len(board._by_hex)}, "
          f"by reg: {len(board._by_reg)}, "
          f"by callsign: {len(board._by_callsign)}")

    print("\n  sample board identifiers:")
    shown = 0
    for hexid, entries in board._by_hex.items():
        e = entries[0]
        print(f"    hex={hexid!r:10} reg={e.reg!r:10} cs={e.callsign!r:10} "
              f"{e.number:9} {e.direction[:3]} {e.place[:20]}")
        shown += 1
        if shown >= 8:
            break
    if not shown:
        print("    NONE - no board entry carries a Mode-S hex.")

    print("\nFetching aircraft in range...")
    try:
        aircraft = live_aircraft()
    except Exception as exc:  # noqa: BLE001
        print(f"  failed: {exc}")
        return 1
    print(f"  {len(aircraft)} aircraft\n")

    print("=" * 70)
    print(f"{'callsign':10} {'hex':8} {'reg':9} -> match")
    print("=" * 70)

    matched = 0
    for ac in aircraft:
        cs = (ac.get("flight") or "").strip()
        hexid = ac.get("hex") or ""
        reg = ac.get("r") or ""
        entry = board.lookup(hexid=hexid, reg=reg, callsign=cs)
        if entry:
            matched += 1
            print(f"{cs:10} {hexid:8} {reg:9} -> {entry.number:9} "
                  f"{entry.preposition} {entry.place}")
        else:
            # Say which key would have worked, if any.
            reasons = []
            if _norm_hex(hexid) in board._by_hex:
                reasons.append("hex IS on board (lookup bug!)")
            if _norm_reg(reg) in board._by_reg:
                reasons.append("reg IS on board (lookup bug!)")
            if _norm_callsign(cs) in board._by_callsign:
                reasons.append("callsign IS on board (lookup bug!)")
            why = "; ".join(reasons) if reasons else "not on the board"
            print(f"{cs:10} {hexid:8} {reg:9} -> {why}")

    print("=" * 70)
    print(f"{matched}/{len(aircraft)} aircraft matched the board.\n")

    # Cross-check the other way: which board flights are airborne near us?
    live_hexes = {_norm_hex(a.get("hex")) for a in aircraft}
    overlap = live_hexes & set(board._by_hex)
    print(f"Hex values present on BOTH sides: {len(overlap)}")
    if overlap:
        print("  ", ", ".join(sorted(overlap)))

    if not matched and board._by_hex:
        print("\nBoard has hexes and aircraft are in range, but nothing "
              "matched.\nEither none of these particular aircraft are on "
              "today's board (very\npossible for overflights), or the "
              "identifiers are formatted differently.\nCompare the two lists "
              "above and send me the output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
