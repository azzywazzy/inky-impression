#!/usr/bin/env python3
"""Draw a test card. No network, no APIs - just the panel and this code.

    python selftest.py             # push it to the panel
    python selftest.py --preview   # save selftest.png instead

Run this after Pimoroni's stripes.py and before running any real app. If
stripes.py works but this doesn't, the problem is in this project rather than
your hardware or the Inky library, which narrows things down a lot.

It also answers the one question I can't answer for you: whether the on-screen
A-D legend lines up with your physical buttons. Each cell is numbered in the
order it appears on screen, top to bottom. Press each button in turn - if the
button you press doesn't match the position you expected, change
BUTTON_STRIP in config.py to "bottom" or "right".
"""

from __future__ import annotations

import sys

from PIL import ImageDraw

import config
from inkyapps import layout
from inkyapps.layout import (BLACK, BLUE, GREEN, ORANGE, RED, WHITE, YELLOW,
                             font, text_width)

WIDTH, HEIGHT = 600, 448

SWATCHES = [
    (BLACK, "BLACK"), (WHITE, "WHITE"), (RED, "RED"), (GREEN, "GREEN"),
    (BLUE, "BLUE"), (YELLOW, "YELLOW"), (ORANGE, "ORANGE"),
]


def build(w: int, h: int):
    img = layout.new_canvas(w, h)
    # Show all four buttons as if mapped, so you can check the alignment.
    box = layout.draw_button_strip(
        img, {"A": "one", "B": "two", "C": "three", "D": "four"},
        "two", config.BUTTON_STRIP)
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    layout.draw_header(draw, box, "Self test", "inky-apps")

    y = y0 + layout.HEADER_H + 14

    # Palette check: every ink the panel can produce, undithered.
    sw_w = (x1 - x0 - 28) // len(SWATCHES)
    for i, (colour, label) in enumerate(SWATCHES):
        sx = x0 + 14 + i * sw_w
        draw.rectangle((sx, y, sx + sw_w - 4, y + 54), fill=colour,
                       outline=BLACK, width=1)
        f = font(10, bold=True)
        draw.text((sx + (sw_w - 4 - text_width(label, f)) / 2, y + 60), label,
                  fill=BLACK, font=f)
    y += 84

    # Font check at the sizes the apps actually use.
    for size, bold in ((26, True), (18, False), (13, False), (11, False)):
        draw.text((x0 + 14, y), f"{size}px  Sphinx of black quartz, judge my vow",
                  fill=BLACK, font=font(size, bold=bold))
        y += size + 10

    y += 6
    draw.line((x0 + 14, y, x1 - 14, y), fill=BLACK, width=1)
    y += 12

    fi = font(13)
    for line in (
        "Do the labels above line up with your physical buttons?",
        'If not, set BUTTON_STRIP = "bottom" or "right" in config.py.',
    ):
        draw.text((x0 + 14, y), line, fill=BLUE, font=fi)
        y += 19

    draw.text((x0 + 14, y1 - 26),
              f"strip: {config.BUTTON_STRIP}   canvas: {w}x{h}",
              fill=BLACK, font=font(11))
    return img


def main(argv: list[str]) -> int:
    preview = "--preview" in argv

    if preview:
        build(WIDTH, HEIGHT).convert("RGB").save("selftest.png")
        print("wrote selftest.png")
        return 0

    from inkyapps.display import Panel
    panel = Panel(saturation=config.SATURATION)
    print(f"panel reports {panel.width}x{panel.height}")
    if (panel.width, panel.height) != (WIDTH, HEIGHT):
        print(f"note: expected {WIDTH}x{HEIGHT} for a 5.7\" Impression")
    print("refreshing - this takes about 30 seconds...")
    panel.show(build(panel.width, panel.height))
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
