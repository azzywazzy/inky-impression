"""Where's it going? Flight routes from a callsign, via adsbdb.com.

    GET https://api.adsbdb.com/v0/callsign/EXS811

returns

    {"response": {"flightroute": {
        "callsign": "EXS811",
        "airline": {"name": "Jet2", "icao": "EXS", ...},
        "origin":      {"iata_code": "LBA", "municipality": "Leeds", ...},
        "destination": {"iata_code": "PMI", "municipality": "Palma de Mallorca", ...}
    }}}

We used to use adsb.lol's /api/0/routeset. That endpoint now answers HTTP 201
with a zero-length body - it accepts the POST and returns nothing - so there
was no data to parse. adsbdb is a curated callsign-to-route database, needs no
key, and usefully carries the operator name as well.

It's one request per callsign rather than a batch, so we cap how many new ones
we look up per poll and space them out. In practice the cache means a handful
of requests an hour: callsigns repeat daily and results are good for hours.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

log = logging.getLogger(__name__)

ENDPOINT = "https://api.adsbdb.com/v0/callsign/{callsign}"
USER_AGENT = "inky-apps/1.0 (personal e-ink display)"

CACHE_TTL_S = 12 * 3600    # routes barely change; callsigns repeat daily
NEGATIVE_TTL_S = 6 * 3600  # unknown stays unknown for a good while
MAX_PER_POLL = 8           # new callsigns to resolve per poll
REQUEST_GAP_S = 0.25       # be polite; the service is free and rate limited


class Route:
    __slots__ = ("origin", "destination", "origin_iata", "destination_iata",
                 "airline", "plausible", "legs", "origin_pos", "dest_pos",
                 "number", "source")

    def __init__(self, origin="", destination="", origin_iata="",
                 destination_iata="", airline="", plausible=True, legs=(),
                 origin_pos=None, dest_pos=None, number="",
                 source="adsbdb"):
        self.origin = origin
        self.destination = destination
        self.origin_iata = origin_iata
        self.destination_iata = destination_iata
        self.airline = airline
        self.plausible = plausible
        self.legs = list(legs)
        # (lat, lon) of each end, when the API gives them - needed to check
        # whether an aircraft could actually be flying this route.
        self.origin_pos = origin_pos
        self.dest_pos = dest_pos
        self.number = number
        # "adsbdb" (callsign guess, needs checking) or "aerodatabox"
        # (airframe lookup, authoritative).
        self.source = source

    @property
    def authoritative(self) -> bool:
        return self.source != "adsbdb"

    def __bool__(self) -> bool:
        return bool(self.origin_iata or self.destination_iata)

    def short(self) -> str:
        """'LBA -> PMI'."""
        if not self:
            return ""
        return f"{self.origin_iata} \u2192 {self.destination_iata}"

    def long(self) -> str:
        """'Leeds -> Palma de Mallorca'."""
        if not (self.origin or self.destination):
            return ""
        return f"{self.origin} \u2192 {self.destination}"

    def away_end(self, home_iata: str):
        """('to', 'Palma de Mallorca') for a departure, ('from', 'Dublin') for
        an arrival, or None if neither end is your airport.

        One end is always your own airport, so naming it wastes the space the
        interesting end needs.
        """
        if not self.legs or home_iata not in self.legs:
            return None
        if self.legs[0] == home_iata:
            return "to", (self.destination or self.destination_iata)
        if self.legs[-1] == home_iata:
            return "from", (self.origin or self.origin_iata)
        return None

    def direction(self, home_iata: str) -> str:
        """'departure', 'arrival' or 'overflight' relative to your airport."""
        if not self.legs or home_iata not in self.legs:
            return "overflight"
        if self.legs[0] == home_iata:
            return "departure"
        if self.legs[-1] == home_iata:
            return "arrival"
        return "overflight"


_EMPTY = Route()


def _place(node) -> tuple:
    """(display name, IATA code, (lat, lon)) from an adsbdb airport node."""
    if not isinstance(node, dict):
        return "", "", None
    name = node.get("municipality") or node.get("name") or ""
    code = node.get("iata_code") or node.get("icao_code") or ""
    lat, lon = node.get("latitude"), node.get("longitude")
    pos = (float(lat), float(lon)) if isinstance(lat, (int, float)) \
        and isinstance(lon, (int, float)) else None
    return name, code, pos


def _parse(payload) -> Route:
    """Turn one adsbdb response body into a Route."""
    if not isinstance(payload, dict):
        return _EMPTY
    response = payload.get("response")
    if not isinstance(response, dict):
        return _EMPTY          # e.g. {"response": "unknown callsign"}
    fr = response.get("flightroute")
    if not isinstance(fr, dict):
        return _EMPTY

    origin, origin_iata, origin_pos = _place(fr.get("origin"))
    dest, dest_iata, dest_pos = _place(fr.get("destination"))
    if not (origin_iata or dest_iata):
        return _EMPTY

    airline = ""
    if isinstance(fr.get("airline"), dict):
        airline = fr["airline"].get("name") or ""

    return Route(origin=origin, destination=dest, origin_iata=origin_iata,
                 destination_iata=dest_iata, airline=airline, plausible=True,
                 legs=[c for c in (origin_iata, dest_iata) if c],
                 origin_pos=origin_pos, dest_pos=dest_pos)


class RouteCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._routes: dict[str, tuple] = {}

    def get(self, callsign: str):
        """Cached Route, or None if we've never looked this callsign up."""
        with self._lock:
            entry = self._routes.get(callsign.strip().upper())
        if not entry:
            return None
        stored_at, route = entry
        ttl = CACHE_TTL_S if route else NEGATIVE_TTL_S
        if time.time() - stored_at > ttl:
            return None
        return route

    def unknown(self, callsigns) -> list:
        return [c for c in callsigns if c and self.get(c) is None]

    def _fetch_one(self, callsign: str):
        r = requests.get(ENDPOINT.format(callsign=callsign), timeout=12,
                         headers={"Accept": "application/json",
                                  "User-Agent": USER_AGENT})
        if r.status_code == 404:
            return _EMPTY            # adsbdb doesn't know this callsign
        r.raise_for_status()
        try:
            return _parse(r.json())
        except ValueError as exc:
            body = (r.text or "")[:160].replace("\n", " ")
            log.warning("route response wasn't JSON (%s): HTTP %s, %d bytes, "
                        "content-type %r, body %r", exc, r.status_code,
                        len(r.content), r.headers.get("Content-Type", "?"), body)
            return None

    def lookup(self, callsigns, lat: float = 0.0, lon: float = 0.0) -> None:
        """Resolve routes for callsigns we don't already know.

        lat/lon are accepted but unused - kept so the tracker doesn't need to
        care which provider is behind this.
        """
        todo = self.unknown({c.strip().upper() for c in callsigns})[:MAX_PER_POLL]
        if not todo:
            return

        now = time.time()
        resolved = failed = 0
        for i, callsign in enumerate(todo):
            if i:
                time.sleep(REQUEST_GAP_S)
            try:
                route = self._fetch_one(callsign)
            except Exception as exc:  # noqa: BLE001 - routes are decoration
                log.info("route request failed for %s: %s", callsign, exc)
                failed += 1
                continue
            if route is None:
                failed += 1
                continue
            with self._lock:
                self._routes[callsign] = (now, route)
            if route:
                resolved += 1

        log.info("routes: %d resolved, %d unknown, %d failed (of %d asked)",
                 resolved, len(todo) - resolved - failed, failed, len(todo))
