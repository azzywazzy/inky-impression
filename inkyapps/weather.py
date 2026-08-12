"""Weather, sunrise/sunset, UV index and pollen, for the home screen.

Two Open-Meteo endpoints, both free and keyless:

    GET https://api.open-meteo.com/v1/forecast
        ?latitude=..&longitude=..&current=temperature_2m,weather_code
        &daily=temperature_2m_max,temperature_2m_min,uv_index_max,sunrise,sunset,weather_code
        &timezone=auto&forecast_days=1+FORECAST_DAYS

    GET https://air-quality-api.open-meteo.com/v1/air-quality
        ?latitude=..&longitude=..
        &current=alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,olive_pollen,ragweed_pollen
        &timezone=auto

Pollen comes from the CAMS European air-quality model, so it only covers
Europe - fine for the UK, worth knowing if you ever change LATITUDE/LONGITUDE
to somewhere it doesn't reach. Fields outside season or coverage come back
null and are just skipped rather than shown as zero.

None of this changes meaningfully minute to minute, so it's cached for
WEATHER_REFRESH_MINUTES independent of how often the home screen itself
redraws - no reason to hit the network every 10 minutes just to redraw a
clock.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

import requests

import config

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# WMO weather codes, as used by Open-Meteo's `weather_code` field.
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}

POLLEN_FIELDS = {
    "Alder": "alder_pollen", "Birch": "birch_pollen",
    "Grass": "grass_pollen", "Mugwort": "mugwort_pollen",
    "Olive": "olive_pollen", "Ragweed": "ragweed_pollen",
}

# Rough, not clinical: Open-Meteo/CAMS report a raw ug/m3 concentration, not
# the grains/m3 counts pollen forecasts usually quote, and the "real" bands
# differ by species. These bands are just enough to say "worth knowing about"
# vs "ignore it" on a small e-ink display.
POLLEN_BANDS = (
    (10.0, "Low"), (25.0, "Moderate"), (50.0, "High"),
)


def pollen_level(value: float) -> str:
    for threshold, label in POLLEN_BANDS:
        if value < threshold:
            return label
    return "Very high"


def uv_level(value: float) -> str:
    if value < 3:
        return "Low"
    if value < 6:
        return "Moderate"
    if value < 8:
        return "High"
    if value < 11:
        return "Very high"
    return "Extreme"


class ForecastDay:
    __slots__ = ("date", "code", "high_c", "low_c")

    def __init__(self, date, code, high_c, low_c):
        self.date = date            # datetime.date
        self.code = code            # WMO weather_code, or None
        self.high_c = high_c
        self.low_c = low_c

    @property
    def label(self) -> str:
        return self.date.strftime("%a")


class WeatherCache:
    def __init__(self):
        self.refreshed_at = 0.0
        self.last_error: str | None = None

        self.temp_c: float | None = None
        self.code: int | None = None          # raw WMO weather_code
        self.description = ""
        self.high_c: float | None = None
        self.low_c: float | None = None
        self.uv_index: float | None = None
        self.sunrise: datetime | None = None
        self.sunset: datetime | None = None
        self.pollen: dict[str, float] = {}   # species -> ug/m3, present only
        self.forecast: list[ForecastDay] = []   # the next FORECAST_DAYS days

    def due(self) -> bool:
        return (time.time() - self.refreshed_at
                >= config.WEATHER_REFRESH_MINUTES * 60)

    def refresh(self) -> None:
        try:
            self._fetch_forecast()
            self._fetch_air_quality()
            self.last_error = None
        except Exception as exc:  # noqa: BLE001 - weather is an enhancement
            self.last_error = str(exc)[:120]
            log.warning("weather refresh failed: %s", self.last_error)
        # Back off regardless of success, so a flaky endpoint doesn't get
        # hammered every time the home screen redraws.
        self.refreshed_at = time.time()

    def _fetch_forecast(self) -> None:
        days_ahead = max(0, config.FORECAST_DAYS)
        r = requests.get(FORECAST_URL, timeout=15, params={
            "latitude": config.LATITUDE,
            "longitude": config.LONGITUDE,
            "current": "temperature_2m,weather_code",
            "daily": ("temperature_2m_max,temperature_2m_min,uv_index_max,"
                      "sunrise,sunset,weather_code"),
            "timezone": "auto",
            "forecast_days": 1 + days_ahead,
        })
        r.raise_for_status()
        data = r.json()
        current = data.get("current") or {}
        daily = data.get("daily") or {}

        self.temp_c = current.get("temperature_2m")
        self.code = current.get("weather_code")
        self.description = WMO_CODES.get(self.code, "")
        self.high_c = _first(daily.get("temperature_2m_max"))
        self.low_c = _first(daily.get("temperature_2m_min"))
        self.uv_index = _first(daily.get("uv_index_max"))
        self.sunrise = _parse_local(_first(daily.get("sunrise")))
        self.sunset = _parse_local(_first(daily.get("sunset")))

        # Today is index 0 - already shown as the current conditions above,
        # so the forecast strip starts from tomorrow.
        dates = daily.get("time") or []
        highs = daily.get("temperature_2m_max") or []
        lows = daily.get("temperature_2m_min") or []
        codes = daily.get("weather_code") or []
        forecast = []
        for i in range(1, len(dates)):
            date = _parse_date(dates[i])
            if date is None:
                continue
            forecast.append(ForecastDay(
                date=date,
                code=codes[i] if i < len(codes) else None,
                high_c=highs[i] if i < len(highs) else None,
                low_c=lows[i] if i < len(lows) else None,
            ))
        self.forecast = forecast

    def _fetch_air_quality(self) -> None:
        r = requests.get(AIR_QUALITY_URL, timeout=15, params={
            "latitude": config.LATITUDE,
            "longitude": config.LONGITUDE,
            "current": ",".join(POLLEN_FIELDS.values()),
            "timezone": "auto",
        })
        r.raise_for_status()
        current = (r.json().get("current") or {})
        self.pollen = {name: current[field]
                       for name, field in POLLEN_FIELDS.items()
                       if isinstance(current.get(field), (int, float))}

    def dominant_pollen(self):
        """(species, value), whichever is highest right now - or None."""
        if not self.pollen:
            return None
        species = max(self.pollen, key=self.pollen.get)
        return species, self.pollen[species]

    def status(self) -> str:
        if self.last_error:
            return "weather unavailable"
        if not self.refreshed_at:
            return "weather loading"
        mins = int((time.time() - self.refreshed_at) / 60)
        return f"weather {mins}m old"


def _first(values):
    return values[0] if values else None


def _parse_local(text: str | None) -> datetime | None:
    """Open-Meteo times look like '2026-08-14T05:32', already in the
    location's local time since we ask for timezone=auto."""
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def _parse_date(text: str | None):
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
