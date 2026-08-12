"""Daily summary: date, weather, sun times, UV, pollen, and LBA traffic.

Meant to be the first thing you see at your desk - weather comes from
inkyapps/weather.py (cached, low-frequency), and the last/next Leeds
Bradford movement comes straight off the shared airport board
(inkyapps/fids.py's BOARD singleton) that the planes app's tracker already
keeps warm in the background. Neither costs this screen its own API budget.

Redraws every 10 minutes while on screen (so the clock and flight times stay
current); pressing A again while already showing does the same thing on
demand, for free - button presses always re-request the current app, same as
every other screen.

Full-bleed, no button strip - a dashboard reads better with the whole panel
than squeezed into the ~540px left after the legend, and the icons need the
room.
"""

from __future__ import annotations

import math
import os
import time
from datetime import datetime

from PIL import ImageDraw

import config
from inkyapps import fids, layout
from inkyapps.layout import (BLACK, BLUE, GREEN, ORANGE, RED, WHITE, YELLOW,
                             font, text_width, truncate)
from inkyapps.apps.base import App
from inkyapps.weather import WeatherCache, pollen_level, uv_level

LEVEL_COLOUR = {
    "Low": GREEN, "Moderate": YELLOW, "High": ORANGE,
    "Very high": RED, "Extreme": RED,
}


def _relative(when) -> str:
    if when is None:
        return ""
    delta = when.timestamp() - time.time()
    if delta > 30:
        mins = delta / 60
        return f"in {mins:.0f} min" if mins >= 1 else "shortly"
    if delta >= -30:
        return "now"
    mins = -delta / 60
    return f"{mins:.0f} min ago" if mins >= 1 else "just now"


def _flight_text(entry, past: bool) -> str:
    bits = [p for p in (entry.number or entry.reg, entry.airline) if p]
    heading = " · ".join(bits) or "Unknown flight"
    if entry.direction == "arrival":
        verb = "landed" if past else "arrives"
    else:
        verb = "departed" if past else "departs"
    place = f" {entry.preposition} {entry.place}" if entry.place else ""
    return f"{heading} · {verb}{place}"


# --- icons -----------------------------------------------------------------
# Small, flat, hand-drawn shapes rather than bitmap assets - consistent with
# the rest of the project (see planes.py's aircraft silhouette) and free to
# recolour for the 7-colour palette.

def _icon_sun(draw, cx, cy, r, colour=YELLOW):
    for i in range(8):
        a = math.radians(i * 45)
        x1, y1 = cx + math.sin(a) * r * 0.62, cy - math.cos(a) * r * 0.62
        x2, y2 = cx + math.sin(a) * r, cy - math.cos(a) * r
        draw.line((x1, y1, x2, y2), fill=BLACK, width=3)
    rr = r * 0.55
    draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=colour,
                 outline=BLACK, width=2)


def _icon_cloud(draw, cx, cy, w, h, colour=WHITE):
    """One circle "bump" plus a rounded body, body drawn last so its fill
    cleanly overwrites the bump's lower half - reads as a soft cloud."""
    bump_r = h * 0.34
    bx, by = cx - w * 0.14, cy - h * 0.22
    draw.ellipse((bx - bump_r, by - bump_r, bx + bump_r, by + bump_r),
                 fill=colour, outline=BLACK, width=2)
    body = (cx - w / 2, cy - h * 0.12, cx + w / 2, cy + h / 2)
    draw.rounded_rectangle(body, radius=h * 0.32, fill=colour, outline=BLACK,
                           width=2)


def _icon_weather(draw, kind: str, cx, cy, size):
    r = size / 2
    if kind == "clear":
        _icon_sun(draw, cx, cy, r)
    elif kind == "partly":
        _icon_sun(draw, cx - r * 0.2, cy - r * 0.12, r * 0.8)
        _icon_cloud(draw, cx + r * 0.12, cy + r * 0.25, size * 0.85,
                    size * 0.58)
    elif kind == "fog":
        _icon_cloud(draw, cx, cy - r * 0.2, size * 0.9, size * 0.48)
        for dy in (0.32, 0.5, 0.68):
            draw.line((cx - r * 0.78, cy + r * dy, cx + r * 0.78, cy + r * dy),
                      fill=BLACK, width=2)
    elif kind == "rain":
        _icon_cloud(draw, cx, cy - r * 0.28, size * 0.95, size * 0.55)
        for dx in (-0.32, 0.0, 0.32):
            x = cx + r * dx
            draw.line((x, cy + r * 0.24, x - 4, cy + r * 0.68), fill=BLUE,
                      width=3)
    elif kind == "snow":
        _icon_cloud(draw, cx, cy - r * 0.28, size * 0.95, size * 0.55)
        for dx in (-0.32, 0.0, 0.32):
            x, yy = cx + r * dx, cy + r * 0.5
            draw.ellipse((x - 3, yy - 3, x + 3, yy + 3), outline=BLACK,
                         width=2)
    elif kind == "storm":
        _icon_cloud(draw, cx, cy - r * 0.3, size * 0.95, size * 0.5)
        bolt = [(cx + 3, cy + r * 0.1), (cx - 7, cy + r * 0.48),
                (cx - 1, cy + r * 0.48), (cx - 5, cy + r * 0.88),
                (cx + 9, cy + r * 0.4), (cx + 2, cy + r * 0.4)]
        draw.polygon(bolt, fill=ORANGE, outline=BLACK)
    else:   # cloudy / overcast / unknown
        _icon_cloud(draw, cx, cy, size * 0.95, size * 0.6)


WMO_ICON_KIND = {
    0: "clear", 1: "partly", 2: "partly", 3: "cloudy",
    45: "fog", 48: "fog",
    51: "rain", 53: "rain", 55: "rain", 56: "rain", 57: "rain",
    61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain",
    80: "rain", 81: "rain", 82: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow", 85: "snow", 86: "snow",
    95: "storm", 96: "storm", 99: "storm",
}


def _icon_sun_arrow(draw, cx, cy, r, rising: bool):
    draw.line((cx - r, cy, cx + r, cy), fill=BLACK, width=2)
    bbox = (cx - r * 0.62, cy - r * 0.62, cx + r * 0.62, cy + r * 0.62)
    draw.pieslice(bbox, start=180, end=360, fill=YELLOW, outline=BLACK,
                 width=2)
    if rising:
        draw.line((cx, cy - r * 0.95, cx, cy - r * 1.3), fill=BLACK, width=2)
        draw.polygon([(cx - 5, cy - r * 1.15), (cx + 5, cy - r * 1.15),
                     (cx, cy - r * 1.38)], fill=BLACK)
    else:
        draw.line((cx, cy - r * 1.3, cx, cy - r * 0.95), fill=BLACK, width=2)
        draw.polygon([(cx - 5, cy - r * 1.1), (cx + 5, cy - r * 1.1),
                     (cx, cy - r * 0.87)], fill=BLACK)


def _icon_badge(draw, cx, cy, r, label, colour):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour, outline=BLACK,
                 width=2)
    f = font(16, bold=True)
    draw.text((cx - text_width(label, f) / 2, cy - 10), label, fill=BLACK,
              font=f)


def _icon_flower(draw, cx, cy, r, colour):
    pr = r * 0.42
    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
        px, py = cx + dx * r * 0.5, cy + dy * r * 0.5
        draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=colour,
                     outline=BLACK, width=2)
    cr = r * 0.34
    draw.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=YELLOW,
                 outline=BLACK, width=2)


def _icon_plane(draw, cx, cy, size, colour, up: bool):
    if up:
        pts = [(cx, cy - size), (cx - size * 0.8, cy + size * 0.55),
               (cx, cy + size * 0.2), (cx + size * 0.8, cy + size * 0.55)]
    else:
        pts = [(cx, cy + size), (cx - size * 0.8, cy - size * 0.55),
               (cx, cy - size * 0.2), (cx + size * 0.8, cy - size * 0.55)]
    draw.polygon(pts, fill=colour, outline=BLACK)


class HomeApp(App):
    name = "home"
    title = "Home"
    refresh_minutes = 10
    show_buttons = False

    def __init__(self):
        self.weather = WeatherCache()

    def render(self, w: int, h: int):
        now = datetime.now()
        img = layout.new_canvas(w, h)
        box = (0, 0, w, h)
        draw = ImageDraw.Draw(img)
        layout.draw_header(draw, box, self.title, now.strftime("%H:%M"))

        weather, last, next_ = self._data()

        x0, x1 = 26, w - 26
        width = x1 - x0
        y = layout.HEADER_H + 16

        draw.text((x0, y), now.strftime("%A %-d %B"), fill=BLACK,
                  font=font(24, bold=True))
        y += 40

        y = self._draw_weather_hero(draw, weather, x0, x1, y, width)
        y += 14

        y = self._draw_stat_tiles(draw, weather, x0, y, width)
        y += 14

        self._draw_flights(draw, last, next_, x0, y, width, h - y - 18)

        if os.environ.get("INKYAPPS_DEMO"):
            status = "demo data"
        else:
            status = f"{weather.status()} · {fids.BOARD.status() or 'no board'}"
        draw.text((x0, h - 16), truncate(status, font(10), width),
                  fill=BLACK, font=font(10))
        return img

    def _draw_weather_hero(self, draw, weather, x0, x1, y, width) -> int:
        size = 96
        cx, cy = x0 + size / 2, y + size / 2
        kind = WMO_ICON_KIND.get(weather.code, "cloudy")
        if weather.temp_c is None:
            draw.ellipse((x0, y, x0 + size, y + size), outline=BLACK,
                         width=2)
            draw.text((cx - 10, cy - 8), "?", fill=BLACK, font=font(24, bold=True))
        else:
            _icon_weather(draw, kind, cx, cy, size)

        tx = x0 + size + 22
        if weather.temp_c is not None:
            temp = f"{weather.temp_c:.0f}°"
            draw.text((tx, y - 6), temp, fill=BLACK, font=font(46, bold=True))
            tw = text_width(temp, font(46, bold=True))
            if weather.description:
                draw.text((tx + tw + 12, y + 12), weather.description,
                          fill=BLACK, font=font(16))
            if weather.high_c is not None and weather.low_c is not None:
                draw.text((tx, y + 58),
                          f"H {weather.high_c:.0f}°   L {weather.low_c:.0f}°",
                          fill=BLACK, font=font(15))
        else:
            draw.text((tx, y + 30), "Weather unavailable", fill=BLACK,
                      font=font(18, bold=True))

        self._draw_forecast(draw, weather, x1, y, size)
        return y + size

    def _draw_forecast(self, draw, weather, x1, y, row_h) -> None:
        """Next few days, right-aligned into the whitespace beside the
        current-conditions block - only drawn if it actually fits there."""
        days = weather.forecast[:config.FORECAST_DAYS]
        if not days:
            return
        col_w, gap = 76, 6
        total = len(days) * col_w + (len(days) - 1) * gap
        fx0 = x1 - total
        fl, ft = font(12, bold=True), font(12)
        for i, day in enumerate(days):
            cx = fx0 + i * (col_w + gap) + col_w / 2
            draw.text((cx - text_width(day.label, fl) / 2, y), day.label,
                      fill=BLACK, font=fl)
            kind = WMO_ICON_KIND.get(day.code, "cloudy")
            _icon_weather(draw, kind, cx, y + 34, 36)
            if day.high_c is not None and day.low_c is not None:
                temps = f"{day.high_c:.0f}°/{day.low_c:.0f}°"
            else:
                temps = "--"
            draw.text((cx - text_width(temps, ft) / 2, y + 58), temps,
                      fill=BLACK, font=ft)

    def _draw_stat_tiles(self, draw, weather, x0, y, width) -> int:
        tile_h = 96
        gap = 14
        tile_w = (width - 2 * gap) / 3

        dominant = weather.dominant_pollen()
        tiles = [
            ("SUN", self._tile_sun),
            ("UV", self._tile_uv),
            ("POLLEN", self._tile_pollen),
        ]
        for i, (label, fn) in enumerate(tiles):
            tx0 = x0 + i * (tile_w + gap)
            box = (tx0, y, tx0 + tile_w, y + tile_h)
            draw.rounded_rectangle(box, radius=12, outline=BLACK, width=2)
            fn(draw, weather, tx0 + tile_w / 2, y, tile_w, tile_h)
        return y + tile_h

    def _tile_sun(self, draw, weather, cx, y, tile_w, tile_h):
        # The UV/pollen icons are full circles centred on y+34, so their
        # bottom edge (and the gap to the label below) sits at ~y+56. This
        # icon's "bottom" is the horizon line itself, right at its centre -
        # there's no lower half bulging down like a circle - so it needs a
        # lower centre than the other two tiles to leave the same visual gap
        # above the label instead of looking like it's floating up top.
        if weather.sunrise:
            _icon_sun_arrow(draw, cx - 22, y + 50, 20, rising=True)
        if weather.sunset:
            _icon_sun_arrow(draw, cx + 22, y + 50, 20, rising=False)
        rise = weather.sunrise.strftime("%H:%M") if weather.sunrise else "--:--"
        setx = weather.sunset.strftime("%H:%M") if weather.sunset else "--:--"
        text = f"{rise} · {setx}"
        f = font(13, bold=True)
        draw.text((cx - text_width(text, f) / 2, y + tile_h - 26), text,
                  fill=BLACK, font=f)

    def _tile_uv(self, draw, weather, cx, y, tile_w, tile_h):
        if weather.uv_index is not None:
            level = uv_level(weather.uv_index)
            _icon_badge(draw, cx, y + 34, 22, f"{weather.uv_index:.0f}",
                       LEVEL_COLOUR.get(level, WHITE))
            text = f"UV · {level}"
        else:
            draw.ellipse((cx - 22, y + 12, cx + 22, y + 56), outline=BLACK,
                         width=2)
            text = "No data"
        f = font(13, bold=True)
        draw.text((cx - text_width(text, f) / 2, y + tile_h - 26), text,
                  fill=BLACK, font=f)

    def _tile_pollen(self, draw, weather, cx, y, tile_w, tile_h):
        dominant = weather.dominant_pollen()
        if dominant:
            species, value = dominant
            level = pollen_level(value)
            _icon_flower(draw, cx, y + 34, 22, LEVEL_COLOUR.get(level, WHITE))
            text = f"{species} · {level}"
        else:
            draw.ellipse((cx - 22, y + 12, cx + 22, y + 56), outline=BLACK,
                         width=2)
            text = "No data"
        f = font(13, bold=True)
        draw.text((cx - text_width(text, f) / 2, y + tile_h - 26), text,
                  fill=BLACK, font=f)

    def _draw_flights(self, draw, last, next_, x0, y, width, avail_h) -> None:
        card_h = min(108, avail_h)
        box = (x0, y, x0 + width, y + card_h)
        draw.rounded_rectangle(box, radius=12, outline=BLACK, width=2)
        draw.text((x0 + 16, y + 8), "LBA", fill=BLACK, font=font(12, bold=True))

        row_y = y + 30
        row_h = (card_h - 34) / 2
        for label, entry, past, up in (("Last", last, True, False),
                                       ("Next", next_, False, True)):
            colour = RED if up else BLUE
            _icon_plane(draw, x0 + 26, row_y + row_h / 2 - 2, 10, colour, up)
            if entry is None:
                draw.text((x0 + 46, row_y), f"{label}: no data", fill=ORANGE,
                          font=font(13))
            else:
                text = truncate(_flight_text(entry, past), font(13),
                                width - 130)
                draw.text((x0 + 46, row_y), text, fill=BLACK, font=font(13))
                rel = _relative(entry.when)
                if rel:
                    rw = text_width(rel, font(12))
                    draw.text((x0 + width - 16 - rw, row_y + 1), rel,
                              fill=BLUE, font=font(12))
            row_y += row_h

    def _data(self):
        if os.environ.get("INKYAPPS_DEMO"):
            return _demo_weather(), *_demo_flights()

        weather = self.weather
        if weather.due():
            weather.refresh()

        if fids.BOARD.due():
            fids.BOARD.refresh()
        last, next_ = fids.BOARD.last_and_next()
        return weather, last, next_


def _demo_weather():
    from datetime import timedelta

    from inkyapps.weather import ForecastDay

    w = WeatherCache()
    w.refreshed_at = time.time()
    w.temp_c, w.description, w.code = 18.0, "Partly cloudy", 2
    w.high_c, w.low_c = 21.0, 12.0
    w.uv_index = 5.2
    w.sunrise = datetime.now().replace(hour=5, minute=42, second=0)
    w.sunset = datetime.now().replace(hour=20, minute=38, second=0)
    w.pollen = {"Grass": 28.0, "Birch": 4.0}
    today = datetime.now().date()
    w.forecast = [
        ForecastDay(today + timedelta(days=1), 61, 19.0, 11.0),
        ForecastDay(today + timedelta(days=2), 3, 20.0, 13.0),
        ForecastDay(today + timedelta(days=3), 0, 23.0, 14.0),
    ]
    return w


def _demo_flights():
    from inkyapps.fids import FidsEntry
    now = time.time()
    last = FidsEntry("arrival", {
        "number": "FR 2327", "airline": {"name": "Ryanair"},
        "movement": {"airport": {"name": "Palma De Mallorca"},
                     "runway": "32", "quality": ["Basic", "Live"],
                     "runwayTime": {"utc": _fmt_utc(now - 11 * 60)}},
    })
    next_ = FidsEntry("departure", {
        "number": "LS 811", "airline": {"name": "Jet2"},
        "movement": {"airport": {"name": "Palma de Mallorca"},
                     "runway": "32", "quality": ["Basic", "Live"],
                     "scheduledTime": {"utc": _fmt_utc(now + 26 * 60)}},
    })
    return last, next_


def _fmt_utc(epoch: float) -> str:
    return datetime.utcfromtimestamp(epoch).strftime("%Y-%m-%d %H:%MZ")
