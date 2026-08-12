"""User settings. Edit this file, restart the service.

    sudo systemctl restart inkyapps
"""

# --- Where you are -------------------------------------------------------
# Used by the planes app to work out what is overhead. Decimal degrees.
LATITUDE = 53.850744
LONGITUDE = -1.606299
OBSERVER_ALT_M = 180          # your rough height above sea level, in metres

# --- Planes app ----------------------------------------------------------
SEARCH_RADIUS_NM = 25        # nautical miles, max 250 (airplanes.live limit)

# How often to poll for aircraft, and how long to remember them. The panel
# takes ~30s to refresh, so we poll in the background and answer instantly
# from memory when you press the button. airplanes.live allows 1 request per
# second, so 15 is well within limits. Tighter polling also times the closest
# approach more precisely - at 30s a fast departure is only sampled two or
# three times near you, so "45s ago" could be out by half a poll interval.
PLANES_POLL_SECONDS = 15
PLANES_MEMORY_MINUTES = 10

# --- Your window ---------------------------------------------------------
# Which way your window faces, in degrees true north (0 = N, 90 = E, 180 = S,
# 270 = W), and how much sky you can see through it. Stand at the window with
# your phone's compass and read off the bearing you're facing.
#
# The sky dome shades this wedge, so you can tell at a glance whether an
# aircraft crossed your view or went past behind the house. Set the bearing to
# None to turn the whole feature off.
WINDOW_BEARING = 225        # e.g. 225 = south-west
WINDOW_FOV_DEG = 120        # a typical window sees ~90-140 degrees of sky

# Rank aircraft you could actually see above ones you couldn't. Useful, but
# set False if you'd rather the list was purely closest-and-most-recent.
PLANES_PREFER_WINDOW = True

# How to orient the sky dome:
#   "window" - your window's direction points to the top of the screen, so the
#              picture matches what you see when you look out. Compass labels
#              rotate to suit. Needs WINDOW_BEARING set.
#   "north"  - traditional map orientation, north always up.
DOME_ORIENTATION = "window"

# --- Your local airport --------------------------------------------------
# IATA code: LBA = Leeds Bradford, MAN = Manchester, EDI = Edinburgh.
HOME_AIRPORT_IATA = "LBA"

# The airport's own position. Used to spot aircraft using it even when we have
# no route for them - a private flight won't be in any route database, but if
# it's low and close to the runway it's plainly taking off or landing.
# Leeds Bradford (EGNM). Verify with a right-click in Google Maps if unsure.
HOME_AIRPORT_ICAO = "EGNM"      # ICAO code, for the airport board lookup
HOME_AIRPORT_LAT = 53.8661
HOME_AIRPORT_LON = -1.6606
HOME_AIRPORT_RADIUS_NM = 6      # within this of the field...
HOME_AIRPORT_MAX_ALT_FT = 6000  # ...and below this = using the airport

# --- Airport board (AeroDataBox) -----------------------------------------
# Correct routes for flights using your airport, from its own departures and
# arrivals board. Joined on the aircraft's Mode-S hex, so recycled callsigns
# can't confuse it. adsbdb stays as the fallback for overflights.
# Key from https://rapidapi.com/aedbx-aedbx/api/aerodatabox (free tier).
AERODATABOX_KEY = "57406a121bmshf35a0144a818740p123020jsnd36a3e7695ef"
FIDS_ENABLED = True

# One request covers the whole window, so refreshing every 30 minutes costs
# about 48 requests a day against a 2400/month allowance.
FIDS_REFRESH_MINUTES = 45
FIDS_WINDOW_HOURS = 12
FIDS_OFFSET_MINUTES = -120      # start the window this far in the past

# --- Overflight lookups --------------------------------------------------
# The board only covers flights using your airport. For everything else -
# airliners passing overhead - look the aircraft up individually by Mode-S
# hex. Accurate, but one request per airframe rather than one per airport,
# so it's budgeted.
#
# Rough monthly arithmetic against a 2400 allowance:
#   FIDS every 45 min          ~960/month
#   40 flight lookups a day   ~1200/month
FLIGHT_LOOKUP_ENABLED = True
FLIGHT_LOOKUP_DAILY_BUDGET = 40   # hard cap, persisted across restarts
FLIGHT_LOOKUP_MAX = 4             # only aircraft near the top of the list
FLIGHT_LOOKUP_PER_POLL = 2        # smooths spending on a busy sky
FLIGHT_CACHE_HOURS = 6            # one request covers an airframe's whole day

# --- What to show --------------------------------------------------------
# Hide private and light aircraft, unless they're using your local airport.
# Airliners, cargo and military always show.
PLANES_HIDE_PRIVATE = True

# Score multiplier for aircraft using your airport. Lower ranks them higher,
# so 0.4 makes an LBA departure beat a higher, more distant overflight.
# Set to 1.0 for no preference.
PLANES_LOCAL_BOOST = 0.4

# List order:
#   "time"      - upcoming first (soonest arrival overhead), then those that
#                 have passed, most recent first. Reads as a timeline.
#   "relevance" - closest and most recent first, weighted by the window and
#                 local-airport settings above.
PLANES_SORT = "time"

# How the "time" ordering divides the screen. Past flights are capped so they
# can't crowd out what's still coming, and a minimum number of upcoming slots
# is held back even when the sky behind you is busy.
PLANES_MAX_SHOWN = 6      # most the screen can fit anyway
PLANES_MAX_PAST = 3       # never more than this many that have gone
PLANES_MIN_UPCOMING = 2   # always leave room for at least this many inbound

# How much detail to give flights 2-5 in the list:
#   "compact"  - airline, route and distance on one line. Fits more aircraft,
#                but the longest names truncate.
#   "detailed" - airline on its own line. Always fits, one fewer aircraft.
PLANES_LIST_STYLE = "compact"

# Units for distances on screen: "mi" (statute miles), "nm" (nautical miles)
# or "km". Aviation works in nautical miles, but ordinary miles are easier to
# picture if you're judging how far away something looked.
# Note SEARCH_RADIUS_NM and HOME_AIRPORT_RADIUS_NM stay in nautical miles
# whatever this is set to - the ADS-B API expects them that way.
DISTANCE_UNIT = "mi"

# Look up plausible routes from callsigns via adsb.lol, so the screen can say
# "Leeds -> Palma" instead of just "EXS811". Free, no key, batched into one
# request per poll and cached for hours. Set False to skip it entirely.
PLANES_ROUTE_LOOKUP = True

# Check looked-up routes against the aircraft's actual position and heading,
# and discard ones it can't possibly be flying. Callsigns get recycled, so the
# route database sometimes returns a different flight's journey entirely -
# this catches those rather than displaying them as fact.
PLANES_ROUTE_CHECK = True
MIN_ELEVATION_DEG = 0        # raise to ~10 to ignore aircraft near the horizon
MAX_POSITION_AGE_S = 60      # ignore aircraft whose position is older than this

# --- Buttons -------------------------------------------------------------
# Physical buttons A-D map to app names. Any app in inkyapps/apps/__init__.py
# can go here. Leave a button out (or set None) to make it do nothing.
BUTTON_APPS = {
    "A": None,        # planned: "home" - clock, weather, etc.
    "B": "planes",
    "C": "apod",
    "D": None,        # no plans yet
}

# Which app to draw when the service starts. Set to None to leave whatever is
# already on the panel alone - e-ink keeps its image with no power, so there's
# no need to spend a refresh on every reboot.
STARTUP_APP = "apod"

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
# Get a key at https://api.nasa.gov (free, instant). DEMO_KEY works but is
# rate limited hard.
NASA_API_KEY = "B6uFWX9fNlPlKdQaPUPrU9GNmtcNJRgoiJwlJh5l"

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
