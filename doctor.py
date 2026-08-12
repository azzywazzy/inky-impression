#!/usr/bin/env python3
"""Pre-flight check. Run it after copying files over.

    python doctor.py

Catches the failure mode this project is most prone to: copying some files but
not others, so a screen calls something that doesn't exist yet. That normally
shows up as an AttributeError on the panel, 30 seconds after a button press.
This finds it in about a second instead.

Checks imports, config keys, the attributes modules expect of each other, and
renders every registered app with demo data. No hardware or network needed.
"""

from __future__ import annotations

import os
import sys
import traceback

os.environ.setdefault("INKYAPPS_DEMO", "1")

PASS, FAIL = "  ok  ", " FAIL "
problems: list[str] = []


def check(label: str, fn):
    try:
        detail = fn()
    except Exception as exc:  # noqa: BLE001 - reporting is the whole point
        problems.append(f"{label}: {exc}")
        print(f"[{FAIL}] {label}\n         {type(exc).__name__}: {exc}")
        if os.environ.get("DOCTOR_TRACE"):
            traceback.print_exc()
        return False
    print(f"[{PASS}] {label}" + (f" - {detail}" if detail else ""))
    return True


# --- keys -------------------------------------------------------------
def keys_file():
    import pathlib
    if not (pathlib.Path(__file__).parent / "keys.py").exists():
        raise FileNotFoundError(
            "keys.py not found - copy keys.example.py to keys.py and fill "
            "in your own keys")
    return "found"


# --- config ---------------------------------------------------------------
REQUIRED_CONFIG = [
    "BUTTON_APPS", "BUTTON_STRIP", "STARTUP_APP", "DETAIL_BUTTON",
    "SATURATION", "MIN_REFRESH_INTERVAL_S", "NASA_API_KEY", "CACHE_DIR",
    "APOD_SATURATION", "APOD_CONTRAST", "APOD_FIT",
    "APOD_ASPECT_TOLERANCE",
    "AERODATABOX_KEY", "LATITUDE", "LONGITUDE", "OBSERVER_ALT_M",
    "WINDOW_BEARING", "WINDOW_FOV_DEG", "DOME_ORIENTATION", "HOME_AIRPORT_IATA",
    "HOME_AIRPORT_ICAO", "HOME_AIRPORT_LAT", "HOME_AIRPORT_LON",
    "HOME_AIRPORT_RADIUS_NM", "HOME_AIRPORT_MAX_ALT_FT", "SEARCH_RADIUS_NM",
    "PLANES_POLL_SECONDS", "PLANES_MEMORY_MINUTES", "MIN_ELEVATION_DEG",
    "MAX_POSITION_AGE_S", "FIDS_REFRESH_MINUTES", "FIDS_WINDOW_HOURS",
    "FIDS_OFFSET_MINUTES", "PLANES_MAX_SHOWN", "PLANES_MAX_PAST",
    "PLANES_MIN_UPCOMING", "PLANES_LIST_STYLE", "DISTANCE_UNIT",
    "MORNING_APP", "MORNING_TIME", "WEATHER_REFRESH_MINUTES", "FORECAST_DAYS",
]


def config_keys():
    import config
    missing = [k for k in REQUIRED_CONFIG if not hasattr(config, k)]
    if missing:
        raise AttributeError("config.py is missing: " + ", ".join(missing))
    return f"{len(REQUIRED_CONFIG)} settings present"


def config_sanity():
    import config
    notes = []
    if config.NASA_API_KEY in ("", "PUT_YOUR_KEY_HERE"):
        notes.append("NASA_API_KEY not set (button C will fail)")
    if config.AERODATABOX_KEY in ("", "PUT_YOUR_KEY_HERE"):
        notes.append("AERODATABOX_KEY not set (button B will show no "
                     "flight numbers)")
    if notes:
        raise ValueError("; ".join(notes))
    return "keys look plausible"


# --- cross-module expectations -------------------------------------------
def module_contracts():
    from inkyapps import fids, geo, layout, tracker, weather

    wanted = {
        "layout": (layout, ["new_canvas", "draw_header", "draw_button_strip",
                            "quantize_photo", "prepare_photo", "error_screen",
                            "font", "text_width", "truncate"]),
        "geo": (geo, ["ground_distance_m", "bearing_deg", "elevation_deg",
                      "slant_range_m", "compass_point", "within_arc",
                      "FEET_TO_M", "M_TO_NM"]),
        "fids": (fids, ["FidsBoard", "FidsEntry", "BOARD"]),
        "tracker": (tracker, ["AircraftTracker", "Sighting"]),
        "weather": (weather, ["WeatherCache", "pollen_level", "uv_level"]),
    }
    for name, (mod, attrs) in wanted.items():
        missing = [a for a in attrs if not hasattr(mod, a)]
        if missing:
            raise AttributeError(
                f"{name}.py is out of date - missing {', '.join(missing)}")

    s = tracker.Sighting("abc123")
    for attr in ("hex", "callsign", "reg", "from_window", "airline",
                 "movement", "climb", "age_s", "passed", "local",
                 "worth_showing", "eta_remaining", "approaching",
                 "flight_number", "fids", "route_summary"):
        if not hasattr(s, attr):
            raise AttributeError(
                f"tracker.py is out of date - Sighting has no {attr!r}")

    if not hasattr(fids.BOARD, "last_and_next"):
        raise AttributeError("fids.py is out of date - BOARD has no "
                             "last_and_next")

    w = weather.WeatherCache()
    for attr in ("due", "refresh", "status", "dominant_pollen", "code",
                 "forecast"):
        if not hasattr(w, attr):
            raise AttributeError(
                f"weather.py is out of date - WeatherCache has no {attr!r}")
    return "geo, fids, tracker, weather, layout agree"


def app_registry():
    from inkyapps.apps import REGISTRY
    import config
    mapped = {v for v in config.BUTTON_APPS.values() if v}
    mapped |= {a for a in (config.STARTUP_APP, config.MORNING_APP) if a}
    unknown = mapped - set(REGISTRY)
    if unknown:
        raise KeyError(f"BUTTON_APPS/STARTUP_APP/MORNING_APP points at "
                       f"unregistered app(s): {', '.join(sorted(unknown))}")
    for name, app in REGISTRY.items():
        for attr in ("render", "start", "name", "show_buttons"):
            if not hasattr(app, attr):
                raise AttributeError(f"app {name!r} has no {attr!r} - "
                                     "base.py may be out of date")
    return f"{len(REGISTRY)} app(s): {', '.join(sorted(REGISTRY))}"


def render_all():
    from inkyapps.apps import REGISTRY
    done = []
    for name, app in sorted(REGISTRY.items()):
        img = app.render(600, 448)
        if img.size != (600, 448):
            raise ValueError(f"{name} rendered {img.size}, expected (600, 448)")
        done.append(name)
    return "rendered " + ", ".join(done)


def main() -> int:
    print(f"inky-apps doctor  (Python {sys.version.split()[0]})\n")
    check("keys.py exists (copied from keys.example.py)", keys_file)
    check("config.py has every setting the code expects", config_keys)
    check("config.py values look set up", config_sanity)
    check("modules are mutually consistent", module_contracts)
    check("buttons point at registered apps", app_registry)
    check("every app renders", render_all)

    print()
    if problems:
        print(f"{len(problems)} problem(s) found. Most are a file that didn't "
              "get copied over -\nre-copy the module named above and run this "
              "again.")
        print("\nRe-run with DOCTOR_TRACE=1 for full tracebacks.")
        return 1
    print("All good - safe to run run.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
