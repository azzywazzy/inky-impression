"""Where in the sky is that thing?

Given your position and an aircraft's position + altitude, works out which way
to look and how far up. All angles in degrees, all distances in metres unless
the name says otherwise.
"""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6371008.8
FEET_TO_M = 0.3048
M_TO_NM = 1 / 1852.0
NM_TO_MI = 1.15078      # nautical miles to statute miles
NM_TO_KM = 1.852

COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def ground_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance along the ground (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, 0-360 clockwise from N."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def elevation_deg(ground_m: float, height_m: float) -> float:
    """Angle above the horizon. 90 = directly overhead, 0 = on the horizon.

    Ignores earth curvature and refraction, both of which are noise at the
    distances involved here (tens of km).
    """
    if ground_m <= 1.0:
        return 90.0
    return math.degrees(math.atan2(height_m, ground_m))


def slant_range_m(ground_m: float, height_m: float) -> float:
    """Straight-line distance from you to the aircraft."""
    return math.hypot(ground_m, height_m)


KNOT_TO_MS = 0.514444


def local_offset_m(lat0: float, lon0: float, lat: float, lon: float):
    """(east, north) metres of a point relative to you.

    Flat-earth approximation. Good to a few metres over the tens of km we care
    about here, and it makes the closest-approach maths simple vector algebra.
    """
    dlat = math.radians(lat - lat0)
    dlon = math.radians(lon - lon0)
    north = dlat * EARTH_RADIUS_M
    east = dlon * EARTH_RADIUS_M * math.cos(math.radians((lat0 + lat) / 2.0))
    return east, north


def time_to_closest(east: float, north: float, speed_kt: float,
                    track_deg: float):
    """(seconds until closest approach, closest ground distance in metres).

    Straight-line projection from the aircraft's current position and
    velocity. Returns (None, None) if it's already moving away from you, or if
    we don't have a usable speed.

    Aircraft turn, so this is an estimate - but over the few minutes that
    matter for "look up in a moment" it's close enough, and it degrades
    gracefully because we recompute it on every poll.
    """
    if not speed_kt or speed_kt <= 0:
        return None, None
    v = speed_kt * KNOT_TO_MS
    a = math.radians(track_deg)
    ve, vn = v * math.sin(a), v * math.cos(a)
    vv = ve * ve + vn * vn
    if vv <= 0:
        return None, None

    # Closest approach of the line p + v*t to the origin (you).
    t = -(east * ve + north * vn) / vv
    if t < 0:
        return None, None          # already past the closest point
    ce, cn = east + ve * t, north + vn * t
    return t, math.hypot(ce, cn)


def angle_difference(a: float, b: float) -> float:
    """Smallest angle between two bearings, 0-180."""
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def cross_track_m(lat1: float, lon1: float, lat2: float, lon2: float,
                  lat3: float, lon3: float) -> float:
    """How far point 3 lies off the great circle from point 1 to point 2.

    Used to sanity-check a claimed route: an aircraft flying Shannon to Faro
    should be somewhere near the line between them, not over Yorkshire.
    """
    d13 = ground_distance_m(lat1, lon1, lat3, lon3) / EARTH_RADIUS_M
    t13 = math.radians(bearing_deg(lat1, lon1, lat3, lon3))
    t12 = math.radians(bearing_deg(lat1, lon1, lat2, lon2))
    return abs(math.asin(
        max(-1.0, min(1.0, math.sin(d13) * math.sin(t13 - t12)))
    ) * EARTH_RADIUS_M)


def within_arc(bearing: float, centre: float | None, span: float) -> bool:
    """Is `bearing` inside a `span`-degree arc centred on `centre`?

    Used to work out whether an aircraft was actually in view from your window
    or hidden behind the house. A centre of None means "no window configured",
    in which case everything counts as visible.
    """
    if centre is None:
        return True
    offset = abs(((bearing - centre + 180.0) % 360.0) - 180.0)
    return offset <= span / 2.0


def compass_point(bearing: float) -> str:
    return COMPASS_16[int((bearing % 360.0) / 22.5 + 0.5) % 16]


def look_direction(bearing: float, elevation: float) -> str:
    """A human instruction: 'SSW, 38 up'."""
    return f"{compass_point(bearing)} · {elevation:.0f}° up"
