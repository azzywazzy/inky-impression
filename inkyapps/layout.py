"""Palette, fonts, and the chrome that every app shares.

Everything is drawn into a mode "P" (palette) image whose pixel values are
the panel's own colour indices. That matters: the Inky library passes a "P"
image straight through to the panel with no dithering, so a rectangle you
fill with RED comes out as exactly one colour rather than a stipple of three.
Pass RGB instead (photos, map tiles) and it will dither, which is what you
want for those.
"""

from __future__ import annotations

import functools
import os

from PIL import Image, ImageDraw, ImageFont

# Panel colour indices. These are the values the Inky library itself uses.
BLACK, WHITE, GREEN, BLUE, RED, YELLOW, ORANGE, CLEAN = range(8)

# Index 7 (CLEAN) is the panel's reset colour, not a usable ink - treat it as
# unavailable and never draw with it.
#
# Approximate on-screen appearance, used only for desktop previews. The real
# panel decides what these look like; these are just close enough to judge a
# layout by. Overridden by the library's own palette when it is importable.
_PREVIEW_RGB = [
    (0, 0, 0),        # BLACK
    (255, 255, 255),  # WHITE
    (0, 140, 60),     # GREEN
    (40, 60, 160),    # BLUE
    (200, 40, 40),    # RED
    (230, 200, 40),   # YELLOW
    (220, 120, 40),   # ORANGE
    (255, 255, 255),  # CLEAN
]


@functools.lru_cache(maxsize=1)
def panel_rgb() -> list:
    """The panel's actual colours, from the Inky library if it's installed.

    Falls back to the approximations above so previews still work on a laptop.
    Using the real values matters for dithering: quantising a photo against
    wrong targets pushes the error diffusion in the wrong direction.
    """
    try:
        from inky.inky_uc8159 import DESATURATED_PALETTE
        return [tuple(c) for c in DESATURATED_PALETTE]
    except Exception:
        return list(_PREVIEW_RGB)


def _palette_bytes() -> bytes:
    flat = []
    for rgb in panel_rgb():
        flat.extend(rgb)
    flat.extend([0, 0, 0] * (256 - len(panel_rgb())))
    return bytes(flat)


@functools.lru_cache(maxsize=1)
def _quantise_palette():
    """A 7-entry palette image (CLEAN excluded - it isn't a usable ink)."""
    pal = Image.new("P", (1, 1))
    flat = []
    for rgb in panel_rgb()[:7]:
        flat.extend(rgb)
    flat.extend([0, 0, 0] * (256 - 7))
    pal.putpalette(flat)
    return pal


def quantize_photo(rgb: Image.Image) -> Image.Image:
    """Floyd-Steinberg a photo down to the panel's seven inks.

    Returns a "P" image whose indices are panel colours, so you can paste it
    into a canvas and then draw crisp, undithered UI on top of it.
    """
    out = rgb.convert("RGB").quantize(palette=_quantise_palette(),
                                      dither=Image.Dither.FLOYDSTEINBERG)
    return out.point(lambda p: p if p < 7 else WHITE)


def prepare_photo(img: Image.Image, w: int, h: int,
                  saturation: float = 1.5, contrast: float = 1.15,
                  mode: str = "fill", background: int = BLACK):
    """Fit a photo to w x h and dither it to the panel's inks.

    mode="fill"    crop to fill the box - no borders, but edges are lost.
    mode="contain" fit the whole image inside, padding with `background`.

    E-ink has no backlight, so images look flatter than on a monitor.
    Pimoroni's own advice is to push contrast and saturation before display.
    """
    from PIL import ImageEnhance, ImageOps
    img = ImageOps.exif_transpose(img.convert("RGB"))

    if mode == "contain":
        fitted = img.copy()
        fitted.thumbnail((w, h), Image.LANCZOS)
    else:
        fitted = ImageOps.fit(img, (w, h), method=Image.LANCZOS)

    fitted = ImageEnhance.Color(fitted).enhance(saturation)
    fitted = ImageEnhance.Contrast(fitted).enhance(contrast)
    quantised = quantize_photo(fitted)

    if quantised.size == (w, h):
        return quantised
    # Centre the letterboxed image on a plain background.
    canvas = new_canvas(w, h, background)
    canvas.paste(quantised, ((w - quantised.width) // 2,
                             (h - quantised.height) // 2))
    return canvas


def choose_fit(img_w: int, img_h: int, box_w: int, box_h: int,
               tolerance: float = 0.25) -> str:
    """"fill" if the shapes are close enough that cropping is cheap,
    "contain" if the image is so much taller or wider that filling would
    throw away a big part of it."""
    if not (img_w and img_h and box_w and box_h):
        return "fill"
    relative = (img_w / img_h) / (box_w / box_h)
    return "fill" if 1 / (1 + tolerance) <= relative <= (1 + tolerance) \
        else "contain"


# --- Fonts ---------------------------------------------------------------
# DejaVu ships with Raspberry Pi OS. The Pimoroni installer also gives you
# font_fredoka_one etc. if you prefer something with more character.
_FONT_PATHS = {
    False: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    True: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
}


@functools.lru_cache(maxsize=64)
def font(size: int, bold: bool = False):
    for path in _FONT_PATHS[bold]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def text_width(s: str, f) -> int:
    return int(f.getbbox(s)[2] - f.getbbox(s)[0])


def truncate(s: str, f, max_w: int) -> str:
    """Trim a string with an ellipsis so it fits in max_w pixels."""
    if text_width(s, f) <= max_w:
        return s
    while s and text_width(s + "\u2026", f) > max_w:
        s = s[:-1]
    return s + "\u2026"


# --- Canvas --------------------------------------------------------------

HEADER_H = 44
STRIP_W = 56
STRIP_H = 40


def new_canvas(w: int, h: int, bg: int = WHITE) -> Image.Image:
    img = Image.new("P", (w, h), bg)
    img.putpalette(_palette_bytes())
    return img


def draw_header(draw: ImageDraw.ImageDraw, box, title: str, right: str = "") -> None:
    """Solid title bar across the top of the content area."""
    x0, y0, x1, _ = box
    draw.rectangle((x0, y0, x1, y0 + HEADER_H), fill=BLACK)
    f = font(24, bold=True)
    draw.text((x0 + 12, y0 + 9), title, fill=WHITE, font=f)
    if right:
        fr = font(15)
        draw.text((x1 - 12 - text_width(right, fr), y0 + 16), right,
                  fill=WHITE, font=fr)


def draw_button_strip(img: Image.Image, labels: dict, active: str | None,
                      position: str = "left") -> tuple[int, int, int, int]:
    """Draw the A-D legend and return the (x0, y0, x1, y1) content box left over.

    `labels` maps button letter to the short name shown beside it. The active
    app's button is inverted so you can see at a glance what you're looking at.
    """
    draw = ImageDraw.Draw(img)
    w, h = img.size
    letters = ["A", "B", "C", "D"]

    if position in ("left", "right"):
        x0 = 0 if position == "left" else w - STRIP_W
        draw.rectangle((x0, 0, x0 + STRIP_W, h), fill=WHITE)
        line_x = x0 + STRIP_W if position == "left" else x0
        draw.line((line_x, 0, line_x, h), fill=BLACK, width=2)
        cell = h / 4
        for i, letter in enumerate(letters):
            cy = cell * (i + 0.5)
            name = labels.get(letter)
            on = name is not None and name == active
            box = (x0 + 6, cy - 26, x0 + STRIP_W - 8, cy + 26)
            if on:
                draw.rounded_rectangle(box, radius=8, fill=BLACK)
            elif name:
                draw.rounded_rectangle(box, radius=8, outline=BLACK, width=2)
            fg = WHITE if on else BLACK
            fl = font(20, bold=True)
            draw.text((x0 + 20, cy - 22), letter, fill=fg, font=fl)
            if name:
                fs = font(11)
                label = truncate(name, fs, STRIP_W - 18)
                draw.text((x0 + 10, cy + 2), label, fill=fg, font=fs)
        return ((STRIP_W, 0, w, h) if position == "left"
                else (0, 0, w - STRIP_W, h))

    # bottom
    y0 = h - STRIP_H
    draw.line((0, y0, w, y0), fill=BLACK, width=2)
    cell = w / 4
    for i, letter in enumerate(letters):
        cx = cell * (i + 0.5)
        name = labels.get(letter)
        on = name is not None and name == active
        box = (cx - cell / 2 + 6, y0 + 5, cx + cell / 2 - 6, h - 4)
        if on:
            draw.rounded_rectangle(box, radius=8, fill=BLACK)
        elif name:
            draw.rounded_rectangle(box, radius=8, outline=BLACK, width=2)
        fg = WHITE if on else BLACK
        f = font(15, bold=True)
        s = f"{letter}  {name}" if name else letter
        draw.text((cx - text_width(s, f) / 2, y0 + 11), s, fill=fg, font=f)
    return (0, 0, w, h - STRIP_H)


def error_screen(w: int, h: int, app_name: str, message: str) -> Image.Image:
    """Shown when an app's render() raises, so failures are visible not silent."""
    img = new_canvas(w, h)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, w, 8), fill=RED)
    draw.text((24, 40), "Something went wrong", fill=RED, font=font(30, bold=True))
    draw.text((24, 84), app_name, fill=BLACK, font=font(18, bold=True))
    f = font(14)
    y = 120
    for line in message.split("\n")[:12]:
        draw.text((24, y), truncate(line, f, w - 48), fill=BLACK, font=f)
        y += 20
    draw.text((24, h - 40), "journalctl -u inkyapps -n 50", fill=BLUE,
              font=font(14))
    return img
