"""Correct route data, from your airport's own departures and arrivals board.

    GET https://aerodatabox.p.rapidapi.com/flights/airports/icao/EGNM
        ?offsetMinutes=-120&durationMinutes=720

Why this exists: matching aircraft by callsign is unreliable - callsigns get
recycled and reassigned mid-flight, so a callsign-keyed lookup often answers
for a different flight entirely. The airport's own board doesn't have that
problem, and it carries the aircraft's Mode-S hex, which is the same
identifier ADS-B gives us. Joining on that is exact.

Two useful details from the real response:

- `quality` is ["Basic"] for schedule-only entries and ["Basic", "Live"] once
  a flight has an aircraft assigned. Only live entries carry reg/modeS/
  callSign - which is fine, because an aircraft near you is always live.
- For a departure, `movement.airport` is where it's going; for an arrival,
  where it came from. Either way it's the end that isn't your airport.

This is the only thing in the planes app that costs AeroDataBox quota - kept
to one request per FIDS_REFRESH_MINUTES, however often the tracker polls.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import requests

import config

log = logging.getLogger(__name__)

HOST = "aerodatabox.p.rapidapi.com"
ENDPOINT = "https://" + HOST + "/flights/airports/icao/{icao}"


def _norm_hex(value) -> str:
    return str(value or "").strip().lower()


def _norm_reg(value) -> str:
    return str(value or "").strip().upper().replace("-", "").replace(" ", "")


def _norm_callsign(value) -> str:
    return str(value or "").strip().upper()


def _parse_utc(node):
    """AeroDataBox times look like '2026-08-08 14:55Z'."""
    if not isinstance(node, dict):
        return None
    text = node.get("utc")
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%MZ").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


class FidsEntry:
    __slots__ = ("direction", "number", "airline", "airport_name",
                 "airport_iata", "when", "status", "runway", "reg", "modes",
                 "callsign", "live")

    def __init__(self, direction: str, raw: dict):
        self.direction = direction          # "departure" or "arrival"
        movement = raw.get("movement") or {}
        airport = movement.get("airport") or {}
        aircraft = raw.get("aircraft") or {}
        airline = raw.get("airline") or {}

        self.number = (raw.get("number") or "").strip()
        self.status = raw.get("status") or ""
        self.airline = airline.get("name") or ""
        self.airport_name = airport.get("name") or ""
        self.airport_iata = airport.get("iata") or airport.get("icao") or ""
        self.runway = movement.get("runway") or ""
        self.callsign = _norm_callsign(raw.get("callSign"))
        self.reg = _norm_reg(aircraft.get("reg"))
        self.modes = _norm_hex(aircraft.get("modeS"))
        self.live = "Live" in (movement.get("quality") or [])

        # runwayTime is the real thing when we have it, then the revised
        # estimate, then the published schedule.
        self.when = (_parse_utc(movement.get("runwayTime"))
                     or _parse_utc(movement.get("revisedTime"))
                     or _parse_utc(movement.get("scheduledTime")))

    @property
    def preposition(self) -> str:
        return "to" if self.direction == "departure" else "from"

    @property
    def place(self) -> str:
        return self.airport_name or self.airport_iata

    def seconds_from(self, now: float) -> float:
        if self.when is None:
            return 1e9
        return abs(self.when.timestamp() - now)


class FidsBoard:
    """A cached copy of the airport board, indexed for fast lookup."""

    def __init__(self):
        self._lock = threading.Lock()
        self._by_hex: dict[str, list] = {}
        self._by_reg: dict[str, list] = {}
        self._by_callsign: dict[str, list] = {}
        self._entries: list = []
        self.refreshed_at = 0.0
        self.last_error: str | None = None
        self.entry_count = 0
        self.runway_in_use = ""
        self._warned = ""

    # --- fetching --------------------------------------------------------

    def due(self) -> bool:
        """Is a refresh due? Says why not, once, rather than failing quietly."""
        key = getattr(config, "AERODATABOX_KEY", "")
        if not key or key == "PUT_YOUR_KEY_HERE":
            self._warn("nokey", "AERODATABOX_KEY is not set in keys.py - "
                       "the airport board is unavailable")
            return False

        if not getattr(config, "HOME_AIRPORT_ICAO", ""):
            self._warn("noicao", "HOME_AIRPORT_ICAO is not set in config.py")
            return False

        return (time.time() - self.refreshed_at
                >= config.FIDS_REFRESH_MINUTES * 60)

    def _warn(self, tag: str, message: str) -> None:
        if self._warned != tag:
            self._warned = tag
            log.warning("%s", message)

    def refresh(self) -> None:
        url = ENDPOINT.format(icao=config.HOME_AIRPORT_ICAO)
        params = {"offsetMinutes": config.FIDS_OFFSET_MINUTES,
                  "durationMinutes": config.FIDS_WINDOW_HOURS * 60}
        try:
            r = requests.get(url, params=params, timeout=25, headers={
                "X-RapidAPI-Key": config.AERODATABOX_KEY,
                "X-RapidAPI-Host": HOST,
                "Accept": "application/json",
            })
            remaining = r.headers.get("x-ratelimit-requests-remaining")
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001 - board is an enhancement
            self.last_error = str(exc)[:120]
            # Back off so a bad key doesn't burn the monthly quota.
            self.refreshed_at = time.time()
            log.warning("FIDS refresh failed: %s", self.last_error)
            return

        self._rebuild(data)
        self.refreshed_at = time.time()
        self.last_error = None
        log.info("FIDS: %d flights indexed for %s%s", self.entry_count,
                 config.HOME_AIRPORT_ICAO,
                 f", {remaining} requests left this month" if remaining else "")

    def _rebuild(self, data: dict) -> None:
        by_hex, by_reg, by_cs = {}, {}, {}
        entries = []
        runways = {}

        for direction, key in (("departure", "departures"),
                               ("arrival", "arrivals")):
            for raw in (data.get(key) or []):
                try:
                    entry = FidsEntry(direction, raw)
                except Exception:  # noqa: BLE001 - skip a malformed record
                    continue
                entries.append(entry)
                if entry.modes:
                    by_hex.setdefault(entry.modes, []).append(entry)
                if entry.reg:
                    by_reg.setdefault(entry.reg, []).append(entry)
                if entry.callsign:
                    by_cs.setdefault(entry.callsign, []).append(entry)
                if entry.runway:
                    runways[entry.runway] = runways.get(entry.runway, 0) + 1

        with self._lock:
            self._by_hex, self._by_reg, self._by_callsign = by_hex, by_reg, by_cs
            self._entries = entries
            self.entry_count = len(entries)
            # Whichever runway most recent movements used is the one in use.
            self.runway_in_use = max(runways, key=runways.get) if runways else ""

    # --- lookup ----------------------------------------------------------

    def lookup(self, hexid: str = "", reg: str = "", callsign: str = "",
               movement: str | None = None):
        """Best matching board entry, or None.

        Tries Mode-S hex, then registration, then callsign - strongest
        identifier first. An aircraft can appear twice in the window (it lands,
        then departs again later), so the observed direction disambiguates, and
        failing that the entry nearest to now wins.
        """
        with self._lock:
            candidates = (self._by_hex.get(_norm_hex(hexid))
                          or self._by_reg.get(_norm_reg(reg))
                          or self._by_callsign.get(_norm_callsign(callsign))
                          or [])
        if not candidates:
            return None

        if movement:
            matching = [e for e in candidates if e.direction == movement]
            if matching:
                candidates = matching

        now = time.time()
        return min(candidates, key=lambda e: e.seconds_from(now))

    def last_and_next(self):
        """(most recently gone, soonest coming), either may be None.

        Any movement counts - arrival or departure - since "the last/next
        flight" doesn't distinguish. Restricted to `live` entries (an actual
        aircraft assigned, per AeroDataBox's "Live" quality flag) - a
        schedule-only entry's `when` is just the timetable, not a confirmed
        movement, and reporting "departed 8 min ago" off a delayed or
        cancelled timetable slot would be actively misleading rather than
        just imprecise. This means it sometimes reports nothing even when
        the raw board has entries - that's the honest answer when nothing on
        the board is confirmed.
        """
        with self._lock:
            entries = list(self._entries)
        now = time.time()
        timed = [e for e in entries if e.when is not None and e.live]
        past = [e for e in timed if e.when.timestamp() <= now]
        upcoming = [e for e in timed if e.when.timestamp() > now]
        last = max(past, key=lambda e: e.when.timestamp()) if past else None
        next_ = min(upcoming, key=lambda e: e.when.timestamp()) if upcoming else None
        return last, next_

    def status(self) -> str:
        key = getattr(config, "AERODATABOX_KEY", "")
        if not key or key == "PUT_YOUR_KEY_HERE":
            return "no board key"
        if self.last_error:
            return "board unavailable"
        if not self.refreshed_at:
            return "board loading"
        mins = int((time.time() - self.refreshed_at) / 60)
        note = f"board {mins}m old"
        if self.runway_in_use:
            note += f" · rwy {self.runway_in_use}"
        return note


# One board, shared by every app that wants it (planes, home) - so however
# many screens are interested, the airport is only ever asked once per
# FIDS_REFRESH_MINUTES, not once per app.
BOARD = FidsBoard()
