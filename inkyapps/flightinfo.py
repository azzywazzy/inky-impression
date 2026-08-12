"""Correct routes for overflights, by Mode-S hex.

    GET https://aerodatabox.p.rapidapi.com/flights/icao24/400877

returns every leg that airframe has flown today, each with full departure and
arrival airports, times and status. Because it's keyed on the airframe rather
than the callsign, recycled callsigns can't confuse it - the same fix that made
the airport board reliable, applied to aircraft that aren't using your airport.

Two things shape the design:

- The response covers the whole day, so one request answers for several legs.
  We cache the legs and pick the one bracketing "now" at read time. That's why
  a lookup of 400877 returned BA 384 to Brussels rather than the shuttle to
  Glasgow it flew later - the right leg depends on when you ask.
- Each request covers one aircraft, unlike FIDS which covers a whole airport.
  So there's a daily budget, persisted to disk so a restart can't reset it and
  overspend.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

import config
from inkyapps.routes import Route

log = logging.getLogger(__name__)

HOST = "aerodatabox.p.rapidapi.com"
ENDPOINT = "https://" + HOST + "/flights/icao24/{hexid}"

# A leg counts as "now" if we're between departure and arrival, with slack
# either side for taxi and for schedule drift.
BRACKET_SLACK_S = 30 * 60


def _parse_utc(node):
    if not isinstance(node, dict):
        return None
    text = node.get("utc")
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%MZ").replace(
            tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _event_time(node):
    """Actual time if known, then the revision, then the schedule."""
    if not isinstance(node, dict):
        return None
    return (_parse_utc(node.get("runwayTime"))
            or _parse_utc(node.get("revisedTime"))
            or _parse_utc(node.get("scheduledTime")))


def _airport(node):
    """(display name, iata, (lat, lon)) from a departure/arrival airport."""
    if not isinstance(node, dict):
        return "", "", None
    apt = node.get("airport") or {}
    name = apt.get("municipalityName") or apt.get("shortName") \
        or apt.get("name") or ""
    code = apt.get("iata") or apt.get("icao") or ""
    loc = apt.get("location") or {}
    lat, lon = loc.get("lat"), loc.get("lon")
    pos = (float(lat), float(lon)) if isinstance(lat, (int, float)) \
        and isinstance(lon, (int, float)) else None
    return name, code, pos


def _to_route(leg: dict):
    """Turn one leg into a Route, marked as coming from the airline data."""
    origin, origin_iata, origin_pos = _airport(leg.get("departure"))
    dest, dest_iata, dest_pos = _airport(leg.get("arrival"))
    if not (origin_iata or dest_iata):
        return None
    airline = (leg.get("airline") or {}).get("name") or ""
    return Route(origin=origin, destination=dest, origin_iata=origin_iata,
                 destination_iata=dest_iata, airline=airline, plausible=True,
                 legs=[c for c in (origin_iata, dest_iata) if c],
                 origin_pos=origin_pos, dest_pos=dest_pos,
                 number=(leg.get("number") or "").strip(),
                 source="aerodatabox")


def _pick_leg(legs: list, now: float):
    """The leg the aircraft is on right now, or the nearest one."""
    best, best_gap = None, None
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        dep = _event_time(leg.get("departure"))
        arr = _event_time(leg.get("arrival"))
        if dep and arr and dep - BRACKET_SLACK_S <= now <= arr + BRACKET_SLACK_S:
            return leg                    # airborne on this leg
        reference = dep or arr
        if reference is None:
            continue
        gap = abs(reference - now)
        if best_gap is None or gap < best_gap:
            best, best_gap = leg, gap
    return best


class FlightLookup:
    """Per-aircraft lookups, cached and budgeted."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict[str, tuple] = {}    # hex -> (fetched_at, legs)
        self._budget_day = ""
        self._budget_used = 0
        self._load_budget()

    # --- budget ----------------------------------------------------------

    @property
    def _budget_path(self) -> Path:
        p = Path(config.CACHE_DIR).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p / "flight-budget.json"

    def _load_budget(self) -> None:
        try:
            data = json.loads(self._budget_path.read_text())
            self._budget_day = data.get("date", "")
            self._budget_used = int(data.get("used", 0))
        except Exception:  # noqa: BLE001 - first run, or unreadable
            self._budget_day, self._budget_used = "", 0

    def _save_budget(self) -> None:
        try:
            self._budget_path.write_text(json.dumps(
                {"date": self._budget_day, "used": self._budget_used}))
        except Exception:  # noqa: BLE001 - not worth failing a poll over
            pass

    def _spend(self) -> bool:
        """Take one request from today's allowance, if there is one."""
        today = date.today().isoformat()
        if self._budget_day != today:
            self._budget_day, self._budget_used = today, 0
        if self._budget_used >= config.FLIGHT_LOOKUP_DAILY_BUDGET:
            return False
        self._budget_used += 1
        self._save_budget()
        return True

    @property
    def spent_today(self) -> int:
        return self._budget_used if self._budget_day == date.today().isoformat() \
            else 0

    # --- lookup ----------------------------------------------------------

    def cached_legs(self, hexid: str):
        with self._lock:
            entry = self._cache.get(hexid.lower())
        if not entry:
            return None
        fetched_at, legs = entry
        if time.time() - fetched_at > config.FLIGHT_CACHE_HOURS * 3600:
            return None
        return legs

    def route_for(self, hexid: str, allow_fetch: bool = True):
        """Route this aircraft is flying now, or None.

        Uses the cache without spending quota; only fetches when allowed and
        there's budget left.
        """
        legs = self.cached_legs(hexid)
        if legs is None:
            if not allow_fetch:
                return None
            legs = self._fetch(hexid)
            if legs is None:
                return None
        leg = _pick_leg(legs, time.time())
        return _to_route(leg) if leg else None

    def _fetch(self, hexid: str):
        key = getattr(config, "AERODATABOX_KEY", "")
        if not key or key == "PUT_YOUR_KEY_HERE":
            return None
        if not self._spend():
            log.info("flight lookup budget spent for today (%d)",
                     config.FLIGHT_LOOKUP_DAILY_BUDGET)
            return None

        try:
            r = requests.get(ENDPOINT.format(hexid=hexid.lower()), timeout=20,
                             headers={"X-RapidAPI-Key": key,
                                      "X-RapidAPI-Host": HOST,
                                      "Accept": "application/json"})
            if r.status_code == 404:
                legs = []                 # no flights known for this airframe
            else:
                r.raise_for_status()
                data = r.json()
                legs = data if isinstance(data, list) else [data]
        except Exception as exc:  # noqa: BLE001 - overflight routes are extra
            log.info("flight lookup failed for %s: %s", hexid, exc)
            return None

        with self._lock:
            self._cache[hexid.lower()] = (time.time(), legs)
        log.info("flight lookup %s: %d leg(s), %d/%d used today", hexid,
                 len(legs), self.spent_today,
                 config.FLIGHT_LOOKUP_DAILY_BUDGET)
        return legs
