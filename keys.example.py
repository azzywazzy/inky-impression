"""Template for keys.py - personal API keys and anything identifying.

    cp keys.example.py keys.py

Then fill in your own values. keys.py is listed in .gitignore, so it never
gets committed - config.py imports from it, but the real values stay local
to this machine.
"""

# NASA Astronomy Picture of the Day. Get a key at https://api.nasa.gov
# (free, instant). DEMO_KEY works but is rate limited hard.
NASA_API_KEY = "PUT_YOUR_KEY_HERE"

# AeroDataBox (RapidAPI), for the planes app's airport board. Free tier:
# https://rapidapi.com/aedbx-aedbx/api/aerodatabox
AERODATABOX_KEY = "PUT_YOUR_KEY_HERE"

# Decimal degrees, and your rough height above sea level in metres. Used by
# the planes app to work out what's visible through your window.
LATITUDE = 0.0
LONGITUDE = 0.0
OBSERVER_ALT_M = 0

# Which way your window faces, in degrees true north (0=N, 90=E, 180=S,
# 270=W). None disables the "in view" indicator on the planes app.
WINDOW_BEARING = None
