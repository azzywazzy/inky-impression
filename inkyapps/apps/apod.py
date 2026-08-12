"""NASA Astronomy Picture of the Day.

https://api.nasa.gov/planetary/apod

Two things about this API worth knowing:

1. `hdurl` can be enormous - there's a famous 3857x7804 one. On a Pi Zero 2 W
   that's a bad time. We use `url`, which is typically 1000-2000px and plenty
   for a 600x448 panel.
2. `media_type` is sometimes "video" (a YouTube or Vimeo embed). There's no
   image to show on those days, so we fall back to a text card. Asking for
   thumbs=True gets us a `thumbnail_url` for videos, which we use if present.

The response is cached to disk per date, so pressing the button repeatedly
doesn't re-download the picture or burn API quota.
"""

from __future__ import annotations

import io
import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path

import requests
from PIL import Image, ImageDraw

import config
from inkyapps import layout
from inkyapps.layout import BLACK, BLUE, RED, WHITE, YELLOW, font, truncate
from inkyapps.apps.base import App

log = logging.getLogger(__name__)

ENDPOINT = "https://api.nasa.gov/planetary/apod"
CAPTION_H = 62

# How many days back to walk when the current day isn't published yet. APOD
# appears around 05:00 UTC, so before then "today" legitimately doesn't exist.
FALLBACK_DAYS = 3


def _redact(value: object) -> str:
    """requests puts the full URL in its exceptions, API key and all."""
    text = str(value)
    key = getattr(config, "NASA_API_KEY", "")
    if key and len(key) > 8:
        text = text.replace(key, "<api-key>")
    return text


class ApodApp(App):
    name = "apod"
    title = "Picture of the Day"
    refresh_minutes = None   # it only changes once a day; button press is enough
    show_buttons = False     # the picture gets the whole panel
    has_detail = True        # the detail button shows NASA's explanation

    # --- data ------------------------------------------------------------

    @property
    def cache_dir(self) -> Path:
        p = Path(config.CACHE_DIR).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _get(self, extra: dict) -> dict:
        params = {"api_key": config.NASA_API_KEY, **extra}
        r = requests.get(ENDPOINT, timeout=20, params=params)

        remaining = r.headers.get("X-RateLimit-Remaining")
        if remaining:
            log.info("NASA API calls remaining this hour: %s", remaining)

        r.raise_for_status()
        data = r.json()
        # The API sometimes returns an error object with a 200 status.
        if isinstance(data, dict) and int(data.get("code", 200)) >= 400:
            raise RuntimeError(f"APOD API said: {data.get('msg', data)}")
        return data

    def fetch_metadata(self) -> dict:
        if os.environ.get("INKYAPPS_DEMO"):
            return {
                "date": str(date.today()),
                "title": "Pillars of Creation in Infrared",
                "media_type": "image",
                "copyright": "NASA, ESA, CSA, STScI",
                "explanation": "A demo record used for offline layout work.",
                "url": "demo://image",
            }

        cache = self.cache_dir / f"apod-{date.today()}.json"
        if cache.exists():
            log.info("using cached APOD metadata")
            return json.loads(cache.read_text())

        if not config.NASA_API_KEY or config.NASA_API_KEY == "PUT_YOUR_KEY_HERE":
            raise RuntimeError("NASA_API_KEY is not set in config.py")

        # The APOD API has two long-standing quirks that produce HTTP 500s:
        #   1. thumbs=true fails on some records (nasa/apod-api #59, #62), so
        #      we only ask for thumbnails when we know it's a video.
        #   2. the current day 500s while the day's entry is being published
        #      (nasa/apod-api #155) - yesterday's is fine.
        # So: try latest, then today explicitly, then yesterday.
        attempts = [{}] + [
            {"date": str(date.today() - timedelta(days=n))}
            for n in range(FALLBACK_DAYS + 1)
        ]

        data = None
        for extra in attempts:
            try:
                data = self._get(extra)
                break
            except Exception as exc:  # noqa: BLE001 - try the next fallback
                # Before ~05:00 UTC the current day genuinely isn't published,
                # so these misses are routine rather than alarming.
                log.info("APOD %s unavailable (%s)",
                         extra.get("date", "latest"), _redact(exc)[:80])

        if data is None:
            stale = self._newest_cached()
            if stale:
                log.warning("APOD unreachable - showing the last one we have")
                stale["_stale"] = True
                return stale
            raise RuntimeError(
                "NASA's APOD API is returning errors and nothing is cached. "
                "This is usually temporary - try again shortly."
            )

        # Only now, if it turns out to be a video, ask for a thumbnail.
        if data.get("media_type") != "image" and "thumbnail_url" not in data:
            try:
                data = self._get({"date": data.get("date", str(date.today())),
                                  "thumbs": "true"})
            except Exception as exc:  # noqa: BLE001 - text card is fine
                log.info("thumbnail lookup failed: %s", _redact(exc)[:80])

        (self.cache_dir / f"apod-{data.get('date', date.today())}.json").write_text(
            json.dumps(data))
        self._prune_cache()
        return data

    def _newest_cached(self) -> dict | None:
        files = sorted(self.cache_dir.glob("apod-*.json"), reverse=True)
        for f in files:
            try:
                return json.loads(f.read_text())
            except Exception:  # noqa: BLE001 - skip a corrupt cache entry
                continue
        return None

    def fetch_image(self, meta: dict) -> Image.Image | None:
        """Returns the picture, or None if today's APOD has no still image."""
        if os.environ.get("INKYAPPS_DEMO"):
            return _demo_photo()

        url = meta.get("url")
        if meta.get("media_type") != "image":
            url = meta.get("thumbnail_url")   # videos get a thumbnail if asked
        if not url:
            return None

        stem = self.cache_dir / f"apod-{meta.get('date', 'today')}"
        for existing in self.cache_dir.glob(f"{stem.name}.img*"):
            log.info("using cached APOD image")
            return Image.open(existing)

        r = requests.get(url, timeout=45, stream=True)
        r.raise_for_status()
        blob = io.BytesIO(r.content)
        img = Image.open(blob)
        img.load()

        suffix = os.path.splitext(url)[1][:5] or ".jpg"
        (self.cache_dir / f"{stem.name}.img{suffix}").write_bytes(blob.getvalue())
        return img

    def _prune_cache(self, keep: int = 5) -> None:
        files = sorted(self.cache_dir.glob("apod-*"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep * 2:]:
            old.unlink(missing_ok=True)

    # --- drawing ---------------------------------------------------------

    def render(self, w: int, h: int):
        meta = self.fetch_metadata()
        photo = self.fetch_image(meta)

        img = layout.new_canvas(w, h)
        if self.show_buttons:
            labels = {k: v for k, v in config.BUTTON_APPS.items() if v}
            box = layout.draw_button_strip(img, labels, self.name,
                                           config.BUTTON_STRIP)
        else:
            box = (0, 0, w, h)   # full bleed: the picture gets the whole panel
        x0, y0, x1, y1 = box
        cw, ch = x1 - x0, y1 - y0

        if photo is None:
            self._draw_text_card(img, box, meta)
            return img

        mode = config.APOD_FIT
        if mode == "smart":
            # Compare against the fill target, since that's the crop we'd be
            # deciding whether to accept.
            mode = layout.choose_fit(photo.width, photo.height, cw, ch,
                                     config.APOD_ASPECT_TOLERANCE)

        if mode == "contain":
            # Whole image, above a solid caption band. prepare_photo pads to
            # exactly this size, so the band never covers the picture.
            img.paste(layout.prepare_photo(
                photo, cw, ch - CAPTION_H,
                saturation=config.APOD_SATURATION,
                contrast=config.APOD_CONTRAST,
                mode="contain"), (x0, y0))
        else:
            # Fills the panel; the caption sits on top in a solid band so the
            # text stays readable over any image.
            img.paste(layout.prepare_photo(
                photo, cw, ch,
                saturation=config.APOD_SATURATION,
                contrast=config.APOD_CONTRAST,
                mode="fill"), (x0, y0))

        self._draw_caption(img, box, meta)
        return img

    def render_detail(self, w: int, h: int):
        """NASA's write-up for today's picture.

        Explanations run to a few hundred words, so the body text shrinks to
        fit rather than being cut off at an arbitrary point - and only
        truncates when even the smallest size won't hold it.
        """
        meta = self.fetch_metadata()

        img = layout.new_canvas(w, h)
        draw = ImageDraw.Draw(img)
        box = (0, 0, w, h)
        x0, y0, x1, y1 = box
        layout.draw_header(draw, box, "Picture of the Day",
                           meta.get("date", ""))

        margin = 18
        width = x1 - x0 - margin * 2
        y = y0 + layout.HEADER_H + 14

        ft = font(20, bold=True)
        for line in _wrap(meta.get("title", "Untitled"), ft, width)[:2]:
            draw.text((x0 + margin, y), line, fill=BLACK, font=ft)
            y += 25
        y += 4

        credit = " ".join((meta.get("copyright")
                           or "Public domain \u00b7 NASA").split())
        draw.text((x0 + margin, y), truncate(credit, font(11), width),
                  fill=BLUE, font=font(11))
        y += 20
        draw.line((x0 + margin, y, x1 - margin, y), fill=YELLOW, width=2)
        y += 12

        # Largest size whose wrapped text fits the space left.
        explanation = " ".join((meta.get("explanation") or "").split())
        available = (y1 - 26) - y
        for size in (15, 14, 13, 12, 11, 10):
            fb = font(size)
            spacing = size + 4
            lines = _wrap(explanation, fb, width)
            if len(lines) * spacing <= available:
                break
        else:
            fb, spacing = font(10), 14
            lines = _wrap(explanation, fb, width)

        fits = max(1, available // spacing)
        if len(lines) > fits:
            lines = lines[:fits]
            lines[-1] = truncate(lines[-1] + " \u2026", fb, width)

        for line in lines:
            draw.text((x0 + margin, y), line, fill=BLACK, font=fb)
            y += spacing

        footer = f"press {config.DETAIL_BUTTON} for the picture"
        draw.text((x0 + margin, y1 - 20), footer, fill=BLUE, font=font(11))
        return img

    def _draw_caption(self, img, box, meta):
        draw = ImageDraw.Draw(img)
        x0, y0, x1, y1 = box
        draw.rectangle((x0, y1 - CAPTION_H, x1, y1), fill=BLACK)
        draw.line((x0, y1 - CAPTION_H, x1, y1 - CAPTION_H), fill=YELLOW, width=3)

        ft = font(21, bold=True)
        draw.text((x0 + 14, y1 - CAPTION_H + 10),
                  truncate(meta.get("title", "Untitled"), ft, x1 - x0 - 28),
                  fill=WHITE, font=ft)

        fs = font(12)
        credit = meta.get("copyright", "Public domain \u00b7 NASA")
        credit = " ".join(credit.split())
        prefix = "cached  \u00b7  " if meta.get("_stale") else ""
        sub = f"{prefix}{meta.get('date', '')}   \u00b7   {credit}"
        draw.text((x0 + 14, y1 - CAPTION_H + 38),
                  truncate(sub, fs, x1 - x0 - 28), fill=WHITE, font=fs)

    def _draw_text_card(self, img, box, meta):
        """Used on days when the APOD is a video with no usable thumbnail."""
        draw = ImageDraw.Draw(img)
        x0, y0, x1, y1 = box
        layout.draw_header(draw, box, self.title, meta.get("date", ""))
        y = y0 + layout.HEADER_H + 22

        ft = font(26, bold=True)
        for line in _wrap(meta.get("title", "Untitled"), ft, x1 - x0 - 28):
            draw.text((x0 + 14, y), line, fill=BLACK, font=ft)
            y += 32
        y += 6
        draw.text((x0 + 14, y), "Today's APOD is a video", fill=RED,
                  font=font(15, bold=True))
        y += 28

        fe = font(14)
        for line in _wrap(meta.get("explanation", ""), fe, x1 - x0 - 28):
            if y > y1 - 30:
                break
            draw.text((x0 + 14, y), line, fill=BLACK, font=fe)
            y += 19

        draw.text((x0 + 14, y1 - 24), "apod.nasa.gov", fill=BLUE, font=font(13))


def _wrap(text: str, f, max_w: int) -> list:
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if layout.text_width(trial, f) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _demo_photo(w: int = 900, h: int = 700) -> Image.Image:
    """A synthetic nebula-ish thing, for offline layout work."""
    import math
    import random
    random.seed(7)
    img = Image.new("RGB", (w, h), (4, 2, 20))
    px = img.load()
    for y in range(h):
        for x in range(0, w, 2):
            d = math.hypot(x - w * 0.42, y - h * 0.45) / (w * 0.5)
            g = max(0.0, 1.0 - d) ** 2
            r = int(230 * g + 12)
            gr = int(90 * g * g + 6)
            b = int(200 * g ** 1.4 + 24)
            px[x, y] = (min(r, 255), min(gr, 255), min(b, 255))
            px[min(x + 1, w - 1), y] = (min(r, 255), min(gr, 255), min(b, 255))
    d = ImageDraw.Draw(img)
    for _ in range(400):
        sx, sy = random.randrange(w), random.randrange(h)
        s = random.choice([1, 1, 1, 2, 3])
        d.ellipse((sx, sy, sx + s, sy + s), fill=(255, 255, 240))
    return img
