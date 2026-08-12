"""Register your apps here. The keys are the names used in config.BUTTON_APPS.

clock.py is in this directory but deliberately NOT registered - unregistered
modules are never imported, so they can't break a run.
"""

from inkyapps.apps.base import App
from inkyapps.apps.apod import ApodApp
from inkyapps.apps.planes import PlanesApp

REGISTRY: dict[str, App] = {
    app.name: app for app in (
        ApodApp(),
        PlanesApp(),
        # HomeApp(),     # button A - clock, weather, etc. Not built yet.
    )
}

__all__ = ["App", "REGISTRY"]
