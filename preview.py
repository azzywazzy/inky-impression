#!/usr/bin/env python3
"""Render an app to a PNG without touching the panel.

    python preview.py apod                 # -> preview-apod.png
    INKYAPPS_DEMO=1 python preview.py apod # synthetic data, no network

Use this for layout work. A real refresh costs 30 seconds and a chunk of the
panel's rated lifetime; a PNG costs nothing, so iterate here and only push to
the panel when you like what you see.
"""

from __future__ import annotations

import sys

from inkyapps.apps import REGISTRY

WIDTH, HEIGHT = 600, 448   # Inky Impression 5.7"
SCALE = 1                  # bump to 2 if you want a bigger preview file


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in REGISTRY:
        print("usage: python preview.py <app>")
        print("apps:  " + ", ".join(sorted(REGISTRY)))
        return 1

    name = argv[1]
    img = REGISTRY[name].render(WIDTH, HEIGHT)
    out = img.convert("RGB")
    if SCALE != 1:
        from PIL import Image
        out = out.resize((WIDTH * SCALE, HEIGHT * SCALE), Image.NEAREST)

    path = f"preview-{name}.png"
    out.save(path)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
