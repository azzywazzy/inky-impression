"""Background poller that remembers which aircraft came near you.

The problem this solves: a plane departing Leeds Bradford crosses your window
in a couple of minutes and is identifiable for maybe 30-60 seconds. The panel
takes 30 seconds to refresh. So a display that fetches on button press and
shows "what's overhead now" is guaranteed to be pointing at empty sky.

Instead this polls continuously in the background and keeps a short rolling
memory. When you press the button, the answer is already known: what passed
closest, how long ago, and where you should have been looking.

Polling costs nothing - it's a Pi that's already awake, and airplanes.live
allows one request per second. We use one every 15 by default.

Only tracks aircraft using your local airport (on the FIDS board, or plainly
low and close to the field). Nothing else is worth showing, and skipping
route lookups for everything else is what keeps this quota-free: the only
thing here that costs AeroDataBox requests is fids.py's board refresh.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

import config
from inkyapps import fids, geo

log = logging.getLogger(__name__)

HOSTS = [
    "https://api.airplanes.live/v2",
    "https://api.adsb.lol/v2",   # same response shape, used if the first fails
]

USER_AGENT = "inky-apps/1.0 (personal e-ink display)"

# An aircraft counts as "passed" once it's clearly receding, or once its
# closest approach is comfortably in the past.
RECEDING_RATIO = 1.15
PASSED_AFTER_S = 45


class Sighting:
    """What we know about one aircraft over the recent past."""

    __slots__ = ("hex", "callsign", "type", "reg", "first_seen", "last_seen",
                 "closest_at", "closest_nm", "closest_bearing",
                 "closest_elevation", "closest_alt_ft", "alt_ft", "speed_kt",
                 "track", "baro_rate", "current_nm",
                 "eta_s", "eta_nm", "eta_at", "receding", "at_airport",
                 "fids", "lat", "lon")

    def __init__(self, hexid: str):
        self.hex = hexid
        self.callsign = hexid.upper()
        self.type = ""
        self.reg = ""
        self.first_seen = self.last_seen = time.time()
        self.closest_nm = float("inf")
        self.closest_at = 0.0
        self.closest_bearing = 0.0
        self.closest_elevation = 0.0
        self.closest_alt_ft = 0.0
        self.alt_ft = 0.0
        self.speed_kt = None
        self.track = None
        self.baro_rate = None
        self.current_nm = float("inf")
        self.eta_s = None          # seconds to closest approach, at eta_at
        self.eta_nm = None         # how close it's predicted to get
        self.eta_at = 0.0
        self.receding = False      # velocity says it's moving away from you
        self.at_airport = False    # seen low and close to your local airport
        self.fids = None           # matching entry from the airport board
        self.lat = self.lon = None # last reported position

    @property
    def eta_remaining(self):
        """Seconds until closest approach, counted from now.

        eta_s is measured at the poll that produced it, so subtract the time
        since - otherwise a 15-second-old estimate reads 15 seconds late.
        """
        if self.eta_s is None:
            return None
        return self.eta_s - (time.time() - self.eta_at)

    @property
    def approaching(self) -> bool:
        remaining = self.eta_remaining
        return remaining is not None and remaining > 0

    @property
    def from_window(self) -> bool:
        """Was it in view from your window at its closest approach?"""
        return geo.within_arc(self.closest_bearing, config.WINDOW_BEARING,
                              config.WINDOW_FOV_DEG)

    @property
    def airline(self) -> str:
        if self.fids and self.fids.airline:
            return self.fids.airline
        return "Private / GA"

    @property
    def flight_number(self) -> str:
        """The published flight number ("LS 448"), if the board has it.

        Distinct from the callsign ("EXS36PN"), which is an ATC artefact and
        often bears no resemblance to the number on the departure board.
        """
        if self.fids and self.fids.number:
            return self.fids.number
        return ""

    @property
    def local(self) -> bool:
        """Is it using your local airport?

        Either the board has it, or we saw it low and close to the field -
        which is the only evidence available for private flights, since they
        never appear on the board at all.
        """
        return bool(self.fids) or self.at_airport

    @property
    def worth_showing(self) -> bool:
        return self.local

    @property
    def observed_movement(self):
        """What we actually saw: climbing away from the field, or descending
        into it. None if we have no direct evidence.

        This is first-hand observation, so it outranks the board.
        """
        if not self.at_airport or self.baro_rate is None:
            return None
        if self.baro_rate > 300:
            return "departure"
        if self.baro_rate < -300:
            return "arrival"
        return None

    def route_summary(self):
        """(preposition, place, trusted), or None if there's nothing to say.

        Always board-sourced now, so always trusted when present. No board
        match (typically a private/GA flight) means no route to show.
        """
        if self.fids and self.fids.place:
            return self.fids.preposition, self.fids.place, True
        return None

    @property
    def movement(self) -> str:
        """'departure', 'arrival' or 'unknown'."""
        observed = self.observed_movement
        if observed:
            return observed    # what we saw beats the board
        if self.fids:
            return self.fids.direction
        if self.baro_rate is None:
            return "unknown"
        if self.baro_rate > 300:
            return "departure"
        if self.baro_rate < -300:
            return "arrival"
        return "unknown"

    @property
    def age_s(self) -> float:
        return time.time() - self.closest_at

    @property
    def passed(self) -> bool:
        # A live velocity vector is the best evidence: if the projection says
        # it's still closing, it hasn't passed, whatever the distances say.
        if self.approaching:
            return False
        if self.receding:
            return True            # its own velocity vector says so
        return (self.current_nm > self.closest_nm * RECEDING_RATIO
                or self.age_s > PASSED_AFTER_S)

    @property
    def climb(self) -> str:
        if self.baro_rate is None or abs(self.baro_rate) < 300:
            return "level"
        return "climbing" if self.baro_rate > 0 else "descending"


def _compose(upcoming: list, past: list) -> list:
    """Blend the two halves of the timeline into what the screen shows.

    Past flights are capped, so a quiet spell behind you doesn't fill the
    screen with history; whatever room is left goes to what's still coming,
    never dropping below the configured minimum.
    """
    past = past[:config.PLANES_MAX_PAST]
    room = max(config.PLANES_MIN_UPCOMING,
               config.PLANES_MAX_SHOWN - len(past))
    return upcoming[:room] + past


class AircraftTracker(threading.Thread):
    def __init__(self):
        # NB: avoid attribute names threading.Thread uses internally
        # (_target, _handle, _args, _kwargs, _name, _started).
        super().__init__(daemon=True, name="tracker")
        self._seen: dict[str, Sighting] = {}
        self.board = fids.BOARD    # shared with the home app - see fids.py
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self.last_poll_at = 0.0
        self.last_error: str | None = None
        self.hidden = 0

    # --- polling ---------------------------------------------------------

    def stop(self) -> None:
        self._stopping.set()

    def run(self) -> None:
        while not self._stopping.is_set():
            try:
                self._poll()
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - keep the thread alive
                self.last_error = str(exc)
                log.warning("aircraft poll failed: %s", exc)
            self._stopping.wait(config.PLANES_POLL_SECONDS)

    def _fetch(self) -> list:
        tail = (f"/point/{config.LATITUDE}/{config.LONGITUDE}"
                f"/{config.SEARCH_RADIUS_NM}")
        last = None
        for host in HOSTS:
            try:
                r = requests.get(host + tail, timeout=12,
                                 headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
                return r.json().get("ac", []) or []
            except Exception as exc:  # noqa: BLE001 - try the next mirror
                last = exc
                time.sleep(1.0)   # respect the 1 req/sec limit
        raise RuntimeError(f"no ADS-B source responded: {last}")

    def _poll(self) -> None:
        raw = self._fetch()
        now = time.time()
        with self._lock:
            for ac in raw:
                self._absorb(ac, now)
            self._prune(now)
        self.last_poll_at = now
        self._resolve_board()

    def _resolve_board(self) -> None:
        """Refresh the airport board if due, then match it to what we can see.

        Matching is re-done every poll rather than cached on first sight,
        because a schedule-only entry gains its Mode-S hex once the flight goes
        live - so an aircraft that didn't match five minutes ago may now.
        """
        if self.board.due():
            self.board.refresh()
        if not self.board.entry_count:
            return
        with self._lock:
            sightings = list(self._seen.values())
        for s in sightings:
            s.fids = self.board.lookup(hexid=s.hex, reg=s.reg,
                                       callsign=s.callsign,
                                       movement=s.observed_movement)

    def _absorb(self, ac: dict, now: float) -> None:
        lat, lon, alt = ac.get("lat"), ac.get("lon"), ac.get("alt_baro")
        if lat is None or lon is None or not isinstance(alt, (int, float)):
            return
        if ac.get("seen_pos", 0) > config.MAX_POSITION_AGE_S:
            return

        hexid = ac.get("hex") or ""
        if not hexid:
            return

        ground = geo.ground_distance_m(config.LATITUDE, config.LONGITUDE,
                                       lat, lon)
        height = max(alt * geo.FEET_TO_M - config.OBSERVER_ALT_M, 0.0)
        slant_nm = geo.slant_range_m(ground, height) * geo.M_TO_NM

        s = self._seen.get(hexid)
        if s is None:
            s = self._seen[hexid] = Sighting(hexid)

        s.last_seen = now
        s.callsign = ((ac.get("flight") or "").strip() or ac.get("r")
                      or hexid.upper())
        s.type = ac.get("t") or s.type
        s.reg = ac.get("r") or s.reg
        s.alt_ft = float(alt)
        s.speed_kt = ac.get("gs")
        s.track = ac.get("track")
        s.baro_rate = ac.get("baro_rate")
        s.current_nm = slant_nm
        s.lat, s.lon = lat, lon

        # Low and close to the field: it's using your airport, whether or not
        # the board has it yet. Sticky - once true, stays true for the life
        # of the sighting.
        if alt <= config.HOME_AIRPORT_MAX_ALT_FT and not s.at_airport:
            apt_nm = geo.ground_distance_m(
                config.HOME_AIRPORT_LAT, config.HOME_AIRPORT_LON,
                lat, lon) * geo.M_TO_NM
            if apt_nm <= config.HOME_AIRPORT_RADIUS_NM:
                s.at_airport = True

        # Project the current position and velocity forward to work out when
        # it will be nearest to you - "passing in 3 min" rather than a bare
        # distance. Recomputed every poll, so turns get picked up quickly.
        track, speed = ac.get("track"), ac.get("gs")
        if track is not None and speed:
            east, north = geo.local_offset_m(config.LATITUDE, config.LONGITUDE,
                                             lat, lon)
            eta, miss_m = geo.time_to_closest(east, north, speed, track)
            s.eta_s = eta
            s.eta_nm = miss_m * geo.M_TO_NM if miss_m is not None else None
            s.eta_at = now
            # No ETA despite having a velocity means it's already going away.
            s.receding = eta is None
        else:
            s.eta_s = s.eta_nm = None
            s.receding = False

        if slant_nm < s.closest_nm:
            s.closest_nm = slant_nm
            s.closest_at = now
            s.closest_alt_ft = float(alt)
            s.closest_bearing = geo.bearing_deg(config.LATITUDE,
                                                config.LONGITUDE, lat, lon)
            s.closest_elevation = geo.elevation_deg(ground, height)

    def _prune(self, now: float) -> None:
        cutoff = now - config.PLANES_MEMORY_MINUTES * 60
        for hexid in [h for h, s in self._seen.items() if s.last_seen < cutoff]:
            del self._seen[hexid]

    # --- reading ---------------------------------------------------------

    def recent(self) -> list:
        """Everything worth showing: what's coming, soonest first, then what's
        been, most recent first. Reads like a timeline through now.
        """
        with self._lock:
            items = list(self._seen.values())
        shown = [s for s in items if s.worth_showing]
        self.hidden = len(items) - len(shown)

        upcoming = [s for s in shown if s.approaching]
        past = [s for s in shown if not s.approaching]
        upcoming.sort(key=lambda s: s.eta_remaining or 0.0)
        past.sort(key=lambda s: s.age_s)
        return _compose(upcoming, past)

    def status(self) -> str:
        if self.last_error:
            return "no data"
        if not self.last_poll_at:
            return "starting up"
        age = int(time.time() - self.last_poll_at)
        note = f"updated {age}s ago"
        board = self.board.status()
        if board:
            note += f"  ·  {board}"
        if self.hidden:
            note += f"  ·  {self.hidden} hidden"
        return note
