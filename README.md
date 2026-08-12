# inky-impression

Custom code for my Pimoroni 5.7" Inky Impression, driven by a Raspberry Pi.
Physical buttons A-D switch between small "apps" (currently a NASA photo of
the day and a live nearby-aircraft tracker); an on-screen "detail" button
shows a second, more detailed view of whatever's up.

## Hardware / display

- Pimoroni Inky Impression 5.7" — 600x448, 7-colour e-ink.
- Raspberry Pi with the four edge buttons wired per Pimoroni's examples
  (`inkyapps/buttons.py`, BCM pins A=5, B=6, C=16, D=24).
- A colour refresh takes ~30s and the panel dislikes being hammered, so all
  panel writes go through a single worker thread that coalesces requests
  (`inkyapps/display.py`).

## Setup

Dependencies: `Pillow`, `requests`, `gpiod`, `gpiodevice`, and Pimoroni's
`inky` library (there's no `requirements.txt` yet — install these plus
whatever the `inky` package pulls in).

1. Copy the project onto the Pi. If you download/transfer files as a flat
   folder, run `bash organise.sh` first — it sorts them back into the
   top-level / `inkyapps/` / `inkyapps/apps/` layout Python needs.
2. Edit `config.py` with your location, airport, and API keys (see below).
3. Run `python selftest.py` to check the panel and confirm the on-screen
   button legend matches your physical buttons (adjust `BUTTON_STRIP` in
   `config.py` if not).
4. Run `python doctor.py` — a fast, no-hardware pre-flight check that
   imports every module, checks config keys, and renders each registered
   app with demo data. Run this after any file changes before touching the
   real panel.
5. Run the app: `python run.py`. It's meant to run under systemd for an
   always-on display (no unit file is checked in yet — write one that runs
   `python run.py` and restart with `sudo systemctl restart inkyapps` once
   you have).

## Day-to-day dev tools

- `python preview.py <app>` — renders an app straight to
  `preview-<app>.png` without touching the panel. Use this to iterate on
  layout; a real refresh costs 30s and panel lifetime. Add
  `INKYAPPS_DEMO=1` for synthetic data (e.g. fake aircraft) with no network
  calls.
- `python doctor.py` — pre-flight sanity check (see above).
- `python selftest.py` / `python selftest.py --preview` — test card to
  check panel wiring and button-to-legend alignment.
- `python -m inkyapps.buttons` — print raw button presses, nothing else.
- Flight-data debugging (all read-only against the APIs):
  - `python fidstest.py [--hours N] [--icao XXXX]` — dump the raw
    AeroDataBox airport-board response.
  - `python fidsmatch.py` — show why aircraft currently in range do or
    don't match entries on the airport board.
  - `python routetest.py [CALLSIGN ...]` — raw adsb.lol route lookup for
    callsigns overhead (or given on the command line).
  - `python flighttest.py [hex] [reg] [callsign]` — probe AeroDataBox's
    flight-status endpoint for one aircraft. **Costs API quota** (up to one
    request per candidate path tried).

## Apps

Registered in `inkyapps/apps/__init__.py`; only registered apps are
imported, so a broken unregistered module can't break a run.

- **apod** (button C, also the startup app) — NASA Astronomy Picture of the
  Day, with a detail view (button D) for the full description.
- **planes** (button B) — nearby aircraft from airplanes.live, shown as a
  list plus a "sky dome" oriented to your window, cross-referenced against
  your home airport's arrivals/departures board (AeroDataBox) and
  adsb.lol's route lookup.
- Button A and a "home" app (clock, weather, etc.) are planned but not
  built (`inkyapps/apps/clock.py` exists but is deliberately unregistered).
- A `serve.py` exposing the same renders as JPEGs over HTTP, for a
  battery-powered Inky Frame to pull, is planned (`SERVE_HOST`/`SERVE_PORT`
  in `config.py`) but not built yet.

## Key config (`config.py`)

Edit and `sudo systemctl restart inkyapps` to apply. Highlights:

**Location & window**
- `LATITUDE` / `LONGITUDE` / `OBSERVER_ALT_M` — your position, for working
  out what's overhead.
- `WINDOW_BEARING` (degrees true, e.g. 225 = SW) / `WINDOW_FOV_DEG` — which
  way your window faces and how much sky it shows; the sky dome shades this
  wedge. Set `WINDOW_BEARING = None` to turn the feature off.
- `DOME_ORIENTATION` — `"window"` (your view faces up the screen) or
  `"north"` (map-style, north always up).

**Planes app**
- `SEARCH_RADIUS_NM` — max 250 (airplanes.live limit).
- `PLANES_POLL_SECONDS` / `PLANES_MEMORY_MINUTES` — background poll rate
  and how long aircraft are remembered, so button presses answer instantly
  from memory.
- `PLANES_PREFER_WINDOW` — rank aircraft visible through your window above
  others.
- `PLANES_HIDE_PRIVATE` — hide private/light aircraft unless using the
  local airport; airliners/cargo/military always show.
- `PLANES_LOCAL_BOOST` — score multiplier that ranks local-airport traffic
  higher (lower = higher priority; 1.0 = no preference).
- `PLANES_SORT` — `"time"` (timeline: upcoming, then most-recent-past) or
  `"relevance"` (closest/most recent, weighted).
- `PLANES_MAX_SHOWN` / `PLANES_MAX_PAST` / `PLANES_MIN_UPCOMING` — how the
  "time" ordering divides screen space.
- `PLANES_LIST_STYLE` — `"compact"` (fits more) or `"detailed"` (airline on
  its own line, always fits).
- `DISTANCE_UNIT` — `"mi"`, `"nm"`, or `"km"` for on-screen distances
  (search/airport radii stay in nautical miles regardless).
- `PLANES_ROUTE_LOOKUP` / `PLANES_ROUTE_CHECK` — look up routes from
  callsigns via adsb.lol, and sanity-check them against actual
  position/heading (callsigns get recycled, so this catches stale/wrong
  matches).
- `MIN_ELEVATION_DEG` / `MAX_POSITION_AGE_S` — filter aircraft near the
  horizon / with stale positions.

**Home airport & AeroDataBox (FIDS)**
- `HOME_AIRPORT_IATA` / `HOME_AIRPORT_ICAO` / `HOME_AIRPORT_LAT/LON` —
  identifies your airport, used to spot aircraft using it even with no
  route data (e.g. private flights).
- `HOME_AIRPORT_RADIUS_NM` / `HOME_AIRPORT_MAX_ALT_FT` — how close/low
  counts as "using the airport".
- `AERODATABOX_KEY` — from the free tier at
  https://rapidapi.com/aedbx-aedbx/api/aerodatabox.
- `FIDS_ENABLED` / `FIDS_REFRESH_MINUTES` / `FIDS_WINDOW_HOURS` /
  `FIDS_OFFSET_MINUTES` — airport board polling. Budget note: refreshing
  every 45 min is ~960 requests/month against the 2400/month free
  allowance.
- `FLIGHT_LOOKUP_ENABLED` / `FLIGHT_LOOKUP_DAILY_BUDGET` /
  `FLIGHT_LOOKUP_MAX` / `FLIGHT_LOOKUP_PER_POLL` / `FLIGHT_CACHE_HOURS` —
  per-aircraft AeroDataBox lookups for overflights not on the airport
  board (budgeted separately from FIDS; daily cap persists across
  restarts).

**Buttons**
- `BUTTON_APPS` — maps `"A"`/`"B"`/`"C"`/`"D"` to app names from the
  registry (`None` = unmapped). Currently B = planes, C = apod.
- `STARTUP_APP` — app shown when the service starts (`None` = leave
  whatever's already on the panel, since e-ink holds its image unpowered).
  Currently `"apod"`.
- `DETAIL_BUTTON` — which button shows the current app's detail view
  (`""` to disable). Currently `"D"`.
- `BUTTON_STRIP` — `"left"`/`"bottom"`/`"right"`, whichever edge your
  buttons are physically on, so the on-screen legend lines up.
- `HOLD_D_TO_SHUTDOWN` — hold D for 5s to `sudo poweroff` cleanly.

**APOD app**
- `NASA_API_KEY` — free/instant at https://api.nasa.gov (`DEMO_KEY` works
  but is heavily rate-limited).
- `CACHE_DIR` — where downloaded pictures/API responses are cached
  (default `~/.cache/inkyapps`).
- `APOD_SATURATION` / `APOD_CONTRAST` — pushed before dithering, since
  e-ink has no backlight and looks flatter than a monitor.
- `APOD_FIT` — `"smart"` (crop near-panel shapes, letterbox extreme ones),
  `"fill"` (always crop), or `"contain"` (always letterbox).
- `APOD_ASPECT_TOLERANCE` — how far off-panel-shape `"smart"` will still
  crop rather than letterbox.

**Display / server**
- `SATURATION` — global saturation for photographic (RGB) renders; UI
  screens use exact palette indices and ignore it.
- `MIN_REFRESH_INTERVAL_S` — minimum gap between panel refreshes.
- `SERVE_HOST` / `SERVE_PORT` — for the planned `serve.py` HTTP server
  (not built yet).

> **Heads up:** `config.py` currently has real `AERODATABOX_KEY` and
> `NASA_API_KEY` values committed inline, and it isn't in `.gitignore`.
> Worth moving those to environment variables or gitignoring the file
> before this repo is pushed anywhere public.
