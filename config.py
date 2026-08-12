"""User settings. Edit this file, restart the service.

    sudo systemctl restart inkyapps

API keys and anything identifying live in keys.py instead (gitignored - see
keys.example.py to set it up).
"""

from keys import (AERODATABOX_KEY, LATITUDE, LONGITUDE, NASA_API_KEY,
                  OBSERVER_ALT_M, WINDOW_BEARING)

# --- Buttons -------------------------------------------------------------
# Physical buttons A-D map to app names. Any app in inkyapps/apps/__init__.py
# can go here. Leave a button out (or set None) to make it do nothing.
BUTTON_APPS = {
    "A": "home",
    "B": "planes",
    "C": "apod",
    "D": None,        # no plans yet
}

# Which app to draw when the service starts. Set to None to leave whatever is
# already on the panel alone - e-ink keeps its image with no power, so there's
# no need to spend a refresh on every reboot.
STARTUP_APP = "apod"

# Switch to this app once a day at MORNING_TIME (24h "HH:MM", local time) -
# e.g. so the day's new APOD picture is already up when you sit down at your
# desk, whatever was on screen overnight. Set MORNING_APP to None to disable.
MORNING_APP = "apod"
MORNING_TIME = "06:00"

# Shows a second, more detailed view of whatever app is on screen - the full
# text for the Picture of the Day, for instance. Press again to go back.
# Apps without a detail view simply ignore it. Set to "" to disable.
DETAIL_BUTTON = "D"

# The on-screen button labels are drawn as a strip. On the 5.7" Impression the
# buttons run down the LEFT edge in landscape - if yours don't line up with the
# labels, change this to "bottom" (or "right").
BUTTON_STRIP = "left"

# Hold button D for 5 seconds to shut the Pi down cleanly. Handy for an
# always-on display you don't want to SSH into just to power off safely.
HOLD_D_TO_SHUTDOWN = True

# --- NASA Astronomy Picture of the Day -----------------------------------
# NASA_API_KEY lives in keys.py, imported above.

# Where downloaded pictures and API responses are kept, so pressing the
# button twice doesn't re-download anything.
CACHE_DIR = "~/.cache/inkyapps"

# E-ink has no backlight, so photos look flatter than on a monitor. These
# push colour and contrast before dithering. Tune to taste - 1.0 is untouched.
APOD_SATURATION = 1.5
APOD_CONTRAST = 1.15

# How to fit pictures to the panel. APOD images range from square to extreme
# panoramas, so no single answer suits them all.
#   "smart"   - crop when the shape is close to the panel's, letterbox when
#               filling would throw away a large part of the image.
#   "fill"    - always crop to fill. No borders, but edges are lost.
#   "contain" - always show the whole image, with black borders.
APOD_FIT = "smart"

# How different an image's shape may be before "smart" stops cropping.
# 0.25 means up to a quarter off the panel's own proportions. Lower = crops
# less often and letterboxes more.
APOD_ASPECT_TOLERANCE = 0.25

# --- Planes app: your local airport ---------------------------------------
# Only arrivals/departures at this airport are ever shown - see
# inkyapps/tracker.py for why. IATA/ICAO: LBA/EGNM = Leeds Bradford.
HOME_AIRPORT_IATA = "LBA"
HOME_AIRPORT_ICAO = "EGNM"
HOME_AIRPORT_LAT = 53.8661
HOME_AIRPORT_LON = -1.6606

# Low and close to the field counts as "using the airport", whether or not
# the flight is on the board (a private flight never will be).
HOME_AIRPORT_RADIUS_NM = 6      # within this of the field...
HOME_AIRPORT_MAX_ALT_FT = 6000  # ...and below this = using the airport

# --- Planes app: live tracking (airplanes.live, free, no key) -------------
# How far out to look for aircraft, centred on you (LATITUDE/LONGITUDE in
# keys.py). Only needs to cover final approach/initial climb at your airport,
# not general overhead traffic - keep this modest.
SEARCH_RADIUS_NM = 15

# How often to poll, and how long to remember an aircraft after it's gone.
# airplanes.live allows 1 request/second, so this is nowhere near the limit -
# it's what makes the display feel live.
PLANES_POLL_SECONDS = 15
PLANES_MEMORY_MINUTES = 10

MIN_ELEVATION_DEG = 0        # raise to ~10 to ignore aircraft near the horizon
MAX_POSITION_AGE_S = 60      # ignore aircraft whose position is older than this

# How much sky your window shows, in degrees either side of WINDOW_BEARING
# (keys.py). A typical window sees 90-140 degrees.
WINDOW_FOV_DEG = 120

# How to orient the sky dome:
#   "window" - your window's direction points to the top of the dome, so the
#              picture matches what you see when you look out. Needs
#              WINDOW_BEARING set.
#   "north"  - traditional map orientation, north always up.
DOME_ORIENTATION = "window"

# --- Planes app: airport board (AeroDataBox) -------------------------------
# The ONLY thing in this app that costs AeroDataBox quota. Kept deliberately
# slow - quota was nearly exhausted for the month as of 2026-08-12, so this
# trades freshness for staying inside the remaining budget. Increase once you
# know the plan's real per-call cost.
FIDS_REFRESH_MINUTES = 240   # 4 hours
FIDS_WINDOW_HOURS = 12
FIDS_OFFSET_MINUTES = -120   # start the window this far in the past

# --- Planes app: what's shown -----------------------------------------------
PLANES_MAX_SHOWN = 6      # most the screen can fit anyway
PLANES_MAX_PAST = 3       # never more than this many that have gone
PLANES_MIN_UPCOMING = 2   # always leave room for at least this many inbound

# How much detail to give each row:
#   "compact"  - one line per flight. Fits more.
#   "detailed" - two lines (route/aircraft on its own line). Fewer flights.
PLANES_LIST_STYLE = "compact"

# Units for on-screen distances: "mi", "nm", or "km".
DISTANCE_UNIT = "mi"

# --- Home screen (weather / sun / UV / pollen) ----------------------------
# Open-Meteo, free and keyless, so no daily/monthly budget to worry about -
# but conditions don't change minute to minute, so there's still no reason to
# fetch on every 10-minute redraw. LBA last/next flight comes from the same
# shared airport board as the planes app (inkyapps/fids.py's BOARD), so it
# costs nothing extra here either.
WEATHER_REFRESH_MINUTES = 30

# How many days ahead the mini forecast strip shows (today's own weather is
# always shown separately as the big current-conditions block).
FORECAST_DAYS = 3

# --- Display -------------------------------------------------------------
# Only affects photographic images passed as RGB. UI screens are drawn with
# exact palette indices and ignore this.
SATURATION = 0.6

# Minimum seconds between panel refreshes. E-ink updates take ~30s and the
# panel dislikes being hammered; this stops a button-mashing session from
# queueing up dozens of refreshes.
MIN_REFRESH_INTERVAL_S = 20

# --- Optional HTTP server ------------------------------------------------
# serve.py exposes the same render() functions as JPEGs so a battery-powered
# Inky Frame can pull them. See README.
SERVE_HOST = "0.0.0.0"
SERVE_PORT = 8080
