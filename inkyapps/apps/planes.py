"""What just flew past your window.

Reads from the background tracker rather than fetching on demand. By the time
a 30-second panel refresh finishes, a departing aircraft is long gone - so the
useful question isn't "what's overhead now" but "what passed closest, and how
long ago". The tracker has that answer waiting before you press the button.

Only ever shows Leeds Bradford arrivals/departures - see tracker.py for why.

The sky dome on the left plots each aircraft where it was in your sky at its
closest approach: centre is directly overhead, the outer ring is the horizon.
"""

from __future__ import annotations

import math
import os
from datetime import datetime

from PIL import ImageDraw

import config
from inkyapps import geo, layout
from inkyapps.layout import (BLACK, BLUE, GREEN, ORANGE, RED, WHITE,
                             YELLOW, font, text_width, truncate)
from inkyapps.apps.base import App


def _altitude_colour(feet: float) -> int:
    if feet < 5000:
        return RED
    if feet < 20000:
        return ORANGE
    return BLUE


MOVEMENT = {
    "departure": ("↑ DEPARTED", RED),
    "arrival": ("↓ ARRIVING", BLUE),
    "unknown": ("", BLACK),
}


# Top-view airliner silhouette, nose pointing "up" (negative y), drawn in
# units of roughly 20px tall so it can be scaled to taste. Traced clockwise
# from the nose: fuselage, swept wing, fuselage, tailplane, and back.
PLANE_SHAPE = [
    (0.0, -10.0),
    (1.6, -6.0),
    (1.6, -1.0),
    (9.0, 3.5),
    (9.0, 5.5),
    (1.6, 3.0),
    (1.6, 6.5),
    (4.5, 9.0),
    (4.5, 10.5),
    (0.0, 8.5),
    (-4.5, 10.5),
    (-4.5, 9.0),
    (-1.6, 6.5),
    (-1.6, 3.0),
    (-9.0, 5.5),
    (-9.0, 3.5),
    (-1.6, -1.0),
    (-1.6, -6.0),
]


def _plane_polygon(cx: float, cy: float, heading: float, scale: float):
    """The silhouette centred on (cx, cy) with its nose along `heading`.

    `heading` is a screen angle in degrees clockwise from straight up, so the
    dome's rotation must already have been subtracted.
    """
    a = math.radians(heading)
    ca, sa = math.cos(a), math.sin(a)
    points = []
    for x, y in PLANE_SHAPE:
        x, y = x * scale, y * scale
        points.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return points


# Icon size carries distance. The dome's radial axis is already spoken for -
# it shows elevation angle - so nearness is encoded as size instead.
# Thresholds are in the displayed unit, so the legend reads as round numbers.
ICON_NEAR = 1.0           # this close or nearer, drawn at full size
ICON_FAR = 20.0           # this far or further, drawn at minimum size
ICON_MAX_SCALE = 1.05
ICON_MIN_SCALE = 0.5


def _icon_scale(nm: float) -> float:
    value = _convert(nm)
    span = ICON_FAR - ICON_NEAR
    t = (min(max(value, ICON_NEAR), ICON_FAR) - ICON_NEAR) / span
    return ICON_MAX_SCALE - t * (ICON_MAX_SCALE - ICON_MIN_SCALE)


def _badge(draw, x, y, n, r=8):
    """Numbered disc, drawn identically on the dome and in the list so the
    two can be matched at a glance."""
    draw.ellipse((x, y, x + 2 * r, y + 2 * r), fill=WHITE, outline=BLACK,
                 width=2)
    f = font(11, bold=True)
    label = str(n)
    draw.text((x + r - text_width(label, f) / 2, y + r - 8), label,
              fill=BLACK, font=f)
    return 2 * r


def _convert(nm: float) -> float:
    """Nautical miles into whatever unit is on screen.

    Everything is tracked internally in nautical miles, because that's what
    the ADS-B API works in; conversion happens only for display.
    """
    unit = getattr(config, "DISTANCE_UNIT", "nm")
    if unit == "mi":
        return nm * geo.NM_TO_MI
    if unit == "km":
        return nm * geo.NM_TO_KM
    return nm


def _unit() -> str:
    return getattr(config, "DISTANCE_UNIT", "nm")


def _distance(nm: float) -> str:
    return f"{_convert(nm):.1f} {_unit()}"


def _ago(seconds: float) -> str:
    seconds = max(0.0, seconds)   # clock skew shouldn't produce "-3 min ago"
    if seconds < 90:
        return f"{int(seconds)}s ago"
    return f"{seconds / 60:.0f} min ago"


def _eta(seconds: float, short: bool = False) -> str:
    if seconds < 30:
        return "now" if short else "overhead now"
    if seconds < 90:
        return f"in {int(seconds / 10) * 10}s"
    return f"in {seconds / 60:.0f} min"


def _when(s, short: bool = False) -> str:
    """"in 4 min" if it's still coming, "3 min ago" once it's gone.

    An aircraft still inbound has its closest approach revised on every poll,
    so an "age" for it would always read as the last poll - which is why every
    inbound aircraft used to show the same time. Project forward instead.
    """
    remaining = s.eta_remaining
    if remaining is not None and remaining > 0:
        return _eta(remaining, short)
    if not s.passed:
        # No usable velocity vector - say something honest about distance
        # rather than claiming it's overhead.
        if s.closest_nm <= 2.0:
            return "now" if short else "overhead now"
        return "closing"
    return _ago(s.age_s)


class PlanesApp(App):
    name = "planes"
    title = "Overhead"
    refresh_minutes = None       # button press only
    show_buttons = False         # the dome gets the whole panel

    def __init__(self):
        self.tracker = None

    def start(self) -> None:
        """Called once by run.py. Starts polling so history exists later."""
        if os.environ.get("INKYAPPS_DEMO"):
            return
        from inkyapps.tracker import AircraftTracker
        self.tracker = AircraftTracker()
        self.tracker.start()

    def sightings(self):
        if os.environ.get("INKYAPPS_DEMO"):
            from inkyapps.tracker import _compose
            items = _demo_sightings()
            shown = [s for s in items if s.worth_showing]
            upcoming = [s for s in shown if s.approaching]
            past = [s for s in shown if not s.approaching]
            upcoming.sort(key=lambda s: s.eta_remaining or 0.0)
            past.sort(key=lambda s: s.age_s)
            return _compose(upcoming, past)
        if self.tracker is None:
            return []
        return self.tracker.recent()

    # --- drawing ---------------------------------------------------------

    def render(self, w: int, h: int):
        planes = self.sightings()

        img = layout.new_canvas(w, h)
        if self.show_buttons:
            labels = {k: v for k, v in config.BUTTON_APPS.items() if v}
            box = layout.draw_button_strip(img, labels, self.name,
                                           config.BUTTON_STRIP)
        else:
            box = (0, 0, w, h)
        draw = ImageDraw.Draw(img)
        x0, y0, x1, y1 = box
        layout.draw_header(draw, box, self.title,
                           datetime.now().strftime("%H:%M"))

        top = y0 + layout.HEADER_H
        split = x0 + 350
        # Details first: how many rows fit depends on the featured block, and
        # the dome must number exactly the aircraft the list shows - no more.
        listed = self._draw_details(draw, split + 12, top, x1 - 10, y1, planes)
        self._draw_dome(draw, x0, top, split, y1, planes, listed)
        return img

    def _draw_dome(self, draw, x0, y0, x1, y1, planes, numbered=5):
        cx = (x0 + x1) // 2
        cy = y0 + (y1 - y0) // 2 - 12
        radius = min((x1 - x0) // 2 - 22, (y1 - y0) // 2 - 34)

        # Your window's field of view, shaded underneath everything else.
        # PIL measures pie angles from 3 o'clock clockwise; compass bearings
        # start at 12 o'clock, hence the -90 offset.
        if config.WINDOW_BEARING is not None:
            half = config.WINDOW_FOV_DEG / 2.0
            centre = config.WINDOW_BEARING - self._rotation()
            draw.pieslice((cx - radius, cy - radius, cx + radius, cy + radius),
                          start=centre - half - 90,
                          end=centre + half - 90,
                          fill=YELLOW)
            a = math.radians(centre)
            lx = cx + radius * 0.74 * math.sin(a)
            ly = cy - radius * 0.74 * math.cos(a)
            fw = font(10, bold=True)
            draw.text((lx - text_width("WINDOW", fw) / 2, ly - 5), "WINDOW",
                      fill=BLACK, font=fw)

        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                     outline=BLACK, width=2)
        fring = font(9)
        for elev in (30, 60):
            r = radius * (1 - elev / 90)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=BLACK,
                         width=1)
            # Small angle labels below the centre, where markers cluster least.
            label = f"{elev}°"
            lw = text_width(label, fring)
            lx0, ly0 = cx - lw / 2 - 2, cy + r - 12
            draw.rectangle((lx0, ly0, lx0 + lw + 4, ly0 + 12), fill=WHITE)
            draw.text((lx0 + 2, ly0 - 1), label, fill=BLACK, font=fring)
        draw.line((cx - 6, cy, cx + 6, cy), fill=BLACK, width=1)
        draw.line((cx, cy - 6, cx, cy + 6), fill=BLACK, width=1)

        # Compass labels sit at their true bearings, rotated with the dome, so
        # the picture stays orientable however it's turned.
        fc = font(14, bold=True)
        rot = self._rotation()
        for label, bearing in (("N", 0), ("E", 90), ("S", 180), ("W", 270)):
            a = math.radians(bearing - rot)
            tx = cx + (radius + 15) * math.sin(a) - text_width(label, fc) / 2
            ty = cy - (radius + 15) * math.cos(a) - 8
            draw.text((tx, ty), label, fill=BLACK, font=fc)

        # Only aircraft that appear in the list are plotted - an unlabelled
        # marker with no matching row is just noise.
        for i, s in enumerate(planes[:numbered]):
            px, py = self._project(cx, cy, radius, s.closest_bearing,
                                   s.closest_elevation)
            colour = _altitude_colour(s.closest_alt_ft)
            scale = _icon_scale(s.closest_nm)

            if s.track is None:
                # No heading to point it in - fall back to a plain dot.
                r = max(3, int(5 * scale))
                draw.ellipse((px - r, py - r, px + r, py + r), fill=colour,
                             outline=BLACK, width=1)
            else:
                heading = s.track - self._rotation()
                draw.polygon(_plane_polygon(px, py, heading, scale),
                             fill=colour, outline=BLACK)

            _badge(draw, px + 7, py - 22, i + 1, r=8)

        fl = font(10)
        lx = x0 + 14
        for colour, label in ((RED, "<5k"), (ORANGE, "5-20k"), (BLUE, ">20k")):
            draw.polygon(_plane_polygon(lx, y1 - 18, 0, 0.5), fill=colour,
                         outline=BLACK)
            draw.text((lx + 11, y1 - 23), label, fill=BLACK, font=fl)
            lx += 11 + text_width(label, fl) + 14

        # Size scale: a big one and a small one, with the distances they mean.
        draw.line((lx + 2, y1 - 28, lx + 2, y1 - 8), fill=BLACK, width=1)
        lx += 12
        for scale, value in ((ICON_MAX_SCALE, ICON_NEAR),
                             (ICON_MIN_SCALE, ICON_FAR)):
            draw.polygon(_plane_polygon(lx, y1 - 18, 0, scale * 0.62),
                         fill=BLACK, outline=BLACK)
            label = f"{value:.0f} {_unit()}"
            draw.text((lx + 10, y1 - 23), label, fill=BLACK, font=fl)
            lx += 10 + text_width(label, fl) + 12

    @staticmethod
    def _rotation() -> float:
        """Degrees to subtract from a true bearing to get a screen angle.

        With DOME_ORIENTATION = "window" the dome is turned so your window
        faces the top of the screen - the view matches what you'd actually see
        looking out. Falls back to north-up if no window bearing is set.
        """
        if (config.DOME_ORIENTATION == "window"
                and config.WINDOW_BEARING is not None):
            return float(config.WINDOW_BEARING)
        return 0.0

    @classmethod
    def _project(cls, cx, cy, radius, bearing, elevation):
        r = radius * (1 - max(0.0, min(90.0, elevation)) / 90.0)
        a = math.radians(bearing - cls._rotation())
        return cx + r * math.sin(a), cy - r * math.cos(a)

    def _draw_details(self, draw, x0, y0, x1, y1, planes) -> int:
        """Draw the right-hand column. Returns how many aircraft it listed,
        so the dome can number the same ones."""
        width = x1 - x0
        draw.line((x0 - 12, y0 + 8, x0 - 12, y1 - 10), fill=BLACK, width=1)

        if not planes:
            draw.text((x0, y0 + 26), "Quiet sky", fill=BLACK,
                      font=font(24, bold=True))
            f = font(13)
            note = ("Nothing using LBA in the last "
                    f"{config.PLANES_MEMORY_MINUTES} min")
            y = y0 + 26 + 40   # clear of the title's descenders
            for line in _wrap(note, f, width):
                draw.text((x0, y), line, fill=BLACK, font=f)
                y += 18
            return 0

        top = planes[0]
        y = y0 + 10
        f = font(13)
        fs = font(11)

        badge, badge_colour = MOVEMENT.get(top.movement, ("", BLACK))
        if badge:
            fbg = font(12, bold=True)
            draw.text((x0, y), badge, fill=badge_colour, font=fbg)
            y += 18
        else:
            draw.text((x0, y), "CLOSEST RECENTLY", fill=BLUE, font=font(11, bold=True))
            y += 18

        fb = font(24, bold=True)
        fnum = font(15, bold=True)
        _badge(draw, x0, y + 5, 1, r=9)
        # Callsign large, published flight number beside it in blue - they're
        # often unrelated ("EXS36PN" is really "LS 448").
        number = top.flight_number
        reserve = (text_width(number, fnum) + 10) if number else 0
        callsign = truncate(top.callsign, fb, width - 24 - reserve)
        draw.text((x0 + 24, y), callsign, fill=BLACK, font=fb)
        if number:
            draw.text((x0 + 24 + text_width(callsign, fb) + 10, y + 9),
                      number, fill=BLUE, font=fnum)
        y += 28

        draw.text((x0, y), truncate(top.airline, f, width), fill=BLACK, font=f)
        y += 18

        sub = " · ".join(p for p in (top.type, top.reg) if p)
        if sub:
            draw.text((x0, y), truncate(sub, fs, width), fill=BLACK, font=fs)
            y += 16

        # Route: straight from the airport board, so always trusted when
        # present. No board match (usually private/GA) means no route to show.
        fr = font(15, bold=True)
        summary = top.route_summary()
        if not summary:
            draw.text((x0, y), "no board match", fill=ORANGE, font=font(12))
            y += 20
        else:
            preposition, place, _trusted = summary
            text = f"{preposition} {place}"
            draw.text((x0, y), truncate(text, fr, width), fill=BLUE, font=fr)
            y += 22

        detail = f"{top.closest_alt_ft:,.0f} ft {top.climb}"
        draw.text((x0, y), truncate(detail, f, width), fill=BLACK, font=f)
        y += 22

        # Red once it's gone, blue while it's still on its way in.
        when = _when(top)
        draw.text((x0, y), when, fill=RED if top.passed else BLUE,
                  font=font(20, bold=True))
        y += 25

        if top.approaching and top.eta_nm is not None:
            # Predicted: how close it will get, not how close it has been.
            look = (f"{geo.compass_point(top.closest_bearing)} · "
                    f"will pass {_distance(top.eta_nm)} away")
        else:
            look = (f"{geo.compass_point(top.closest_bearing)} · "
                    f"{top.closest_elevation:.0f}° up · "
                    f"{_distance(top.closest_nm)}")
        draw.text((x0, y), truncate(look, fs, width), fill=BLACK, font=fs)
        y += 16

        if config.WINDOW_BEARING is not None:
            if top.from_window:
                draw.text((x0, y), "✓ across your window", fill=GREEN,
                          font=fs)
            else:
                draw.text((x0, y), "behind the house", fill=ORANGE, font=fs)
            y += 16
        y += 4

        draw.line((x0, y, x1, y), fill=BLACK, width=1)
        y += 10

        fn = font(13, bold=True)
        indent = x0 + 20
        avail = x1 - indent
        # Three-line rows are taller, so stop sooner or they run off the panel.
        row_h = 47 if config.PLANES_LIST_STYLE == "detailed" else 33
        listed = 1                      # the featured aircraft counts as one
        for n, other in enumerate(planes[1:6], start=2):
            if y + row_h > y1 - 18:
                break
            listed = n
            _badge(draw, x0, y, n, r=7)
            mark = {"departure": "↑", "arrival": "↓"}.get(other.movement, "•")
            head = f"{mark} {other.callsign}"
            age = _when(other, short=True)
            age_w = text_width(age, fs)
            head = truncate(head, fn, width - 26 - age_w)
            draw.text((indent, y), head, fill=BLACK, font=fn)
            # Flight number tucked in after the callsign if there's room.
            number = other.flight_number
            if number:
                nx = indent + text_width(head, fn) + 8
                if nx + text_width(number, fs) < x1 - age_w - 8:
                    draw.text((nx, y + 2), number, fill=BLUE, font=fs)
            draw.text((x1 - age_w, y + 2), age,
                      fill=BLACK if other.passed else BLUE, font=fs)
            y += 15

            operator = other.airline
            summary = other.route_summary()
            route_colour = BLUE
            if summary and summary[1]:
                preposition, place, _trusted = summary
                route_text = f"{preposition} {place}"
            else:
                route_text = ""
            nm = _distance(other.closest_nm)

            if config.PLANES_LIST_STYLE == "detailed":
                # Airline on its own line - always fits, but fewer rows.
                draw.text((indent, y), truncate(operator, fs, avail),
                          fill=BLACK, font=fs)
                y += 14
                tail = f"{route_text} · {nm}" if route_text else nm
                draw.text((indent, y), truncate(tail, fs, avail),
                          fill=route_colour, font=fs)
                y += 18
            else:
                # Airline in black, route and distance in blue after it.
                op = truncate(operator, fs, avail)
                draw.text((indent, y), op, fill=BLACK, font=fs)
                used = text_width(op, fs)
                room = avail - used
                if route_text:
                    # Prefer dropping the distance whole to truncating it into
                    # a meaningless fragment - the dome shows position anyway.
                    full = f" · {route_text} · {nm}"
                    tail = full if text_width(full, fs) <= room \
                        else f" · {route_text}"
                else:
                    tail = f" · {nm}"
                draw.text((indent + used, y), truncate(tail, fs, room),
                          fill=route_colour, font=fs)
                y += 18

        status = self.tracker.status() if self.tracker else "demo data"
        draw.text((x0, y1 - 20), truncate(status, fs, width), fill=BLACK, font=fs)
        return listed


def _wrap(text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if text_width(trial, f) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _demo_sightings():
    """Fake history so the layout can be worked on offline."""
    import time
    from inkyapps.tracker import Sighting
    from inkyapps.fids import FidsEntry

    now = time.time()
    spec = [
        # hex, callsign, type, reg, nm, elev, bearing, alt_ft, age_s, baro_rate
        ("4ca1f2", "EXS811", "B738", "G-JZHW", 0.9, 42, 310, 2400, 45, 1800),
        ("406b9a", "RYR7GX", "B38M", "EI-HAT", 1.6, 28, 118, 5200, 150, -1200),
        ("39c204", "AFR1180", "A21N", "F-HTAX", 8.2, 61, 205, 31000, 240, 0),
        ("4ba9d1", "EZY44KL", "A320", "G-EZTA", 3.4, 12, 260, 9800, 420, -900),
        ("4009a8", "GCJKL", "R44", "G-CJKL", 2.2, 20, 45, 1400, 300, 0),
        ("40aa11", "GBXTZ", "C172", "G-BXTZ", 4.1, 15, 70, 2000, 200, 0),
        ("4ca9f0", "TOM7GH", "B38M", "G-TUMC", 5.6, 33, 285, 14000, 330, 1400),
    ]
    out = []
    for hexid, cs, typ, reg, nm, elev, brg, alt, age, rate in spec:
        s = Sighting(hexid)
        s.callsign, s.type, s.reg = cs.strip(), typ, reg
        s.closest_nm, s.closest_elevation = nm, elev
        s.closest_bearing, s.closest_alt_ft = brg, alt
        s.closest_at = now - age
        s.alt_ft, s.track, s.baro_rate = alt, brg, rate
        if hexid.endswith("8"):
            s.current_nm = nm
            s.closest_at = now - 3
            s.eta_s, s.eta_nm, s.eta_at = 190.0, 1.4, now
        elif hexid.endswith("0"):
            s.current_nm = nm
            s.closest_at = now - 3
            s.eta_s, s.eta_nm, s.eta_at = 70.0, 2.2, now
        else:
            s.current_nm = nm * 2
        # LBA movements are flagged local; the light aircraft/overflight are
        # not, so the filter can be seen working.
        s.at_airport = hexid in ("4ca1f2", "406b9a", "4ba9d1", "4009a8")
        board = {
            "4ca1f2": ("departure", "LS 811", "Jet2", "Palma de Mallorca"),
            "406b9a": ("arrival", "FR 2327", "Ryanair", "Palma De Mallorca"),
            "4ba9d1": ("arrival", "U2 6041", "easyJet", "Geneva"),
            "4ca9f0": ("departure", "LS 1729", "TUI Airways", "Tenerife South"),
        }
        if hexid in board:
            d, num, air, place = board[hexid]
            s.fids = FidsEntry(d, {"number": num,
                                   "airline": {"name": air},
                                   "movement": {"airport": {"name": place},
                                                "runway": "32",
                                                "quality": ["Basic", "Live"]}})
        out.append(s)
    return out
