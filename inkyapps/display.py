"""Panel access and the refresh worker.

Everything that touches the panel goes through one thread. That matters more
than it sounds: a colour e-ink update takes roughly 30 seconds and blocks the
whole time, so if button callbacks called show() directly you'd get overlapping
SPI writes and a wedged display.

The worker coalesces requests rather than queueing them. Press A, B, C, D in
quick succession during a refresh and you get the current refresh, then D -
not four refreshes taking two minutes to catch up.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback

from inkyapps import layout

log = logging.getLogger(__name__)


class Panel:
    """Thin wrapper over the Inky library, with a headless fallback."""

    def __init__(self, saturation: float = 0.6):
        self.saturation = saturation
        from inky.auto import auto
        self._inky = auto()
        self.width = self._inky.width
        self.height = self._inky.height
        log.info("panel detected: %dx%d", self.width, self.height)

    def show(self, img) -> None:
        try:
            self._inky.set_image(img, saturation=self.saturation)
        except TypeError:
            # Spectra boards don't take a saturation argument.
            self._inky.set_image(img)
        self._inky.show()


class RefreshWorker(threading.Thread):
    def __init__(self, panel: Panel, registry: dict, min_interval_s: int = 20):
        super().__init__(daemon=True, name="refresh")
        self.panel = panel
        self.registry = registry
        self.min_interval_s = min_interval_s

        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending: tuple | None = None      # (app name, detail?)
        self.current: str | None = None
        self.current_detail = False
        self.last_shown_at: float = 0.0

    def request(self, app_name: str, detail: bool = False) -> None:
        """Ask for `app_name` to be on screen. Safe to call from any thread."""
        if app_name not in self.registry:
            log.warning("no such app: %s", app_name)
            return
        with self._lock:
            self._pending = (app_name, detail)
        self._wake.set()

    def request_detail(self) -> None:
        """Toggle the detail view of whatever is currently showing.

        Apps without one are left alone, so the button is simply inert on
        those screens rather than spending a refresh for no change.
        """
        name = self.current
        if not name:
            return
        if not getattr(self.registry[name], "has_detail", False):
            log.info("%s has no detail view", name)
            return
        self.request(name, not self.current_detail)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stop.is_set():
                return

            with self._lock:
                pending = self._pending

            if pending is None:
                continue
            name, detail = pending

            # Rate limit, but keep the request - don't drop it on the floor.
            wait = self.min_interval_s - (time.monotonic() - self.last_shown_at)
            if wait > 0:
                time.sleep(wait)
                if self._wake.is_set():
                    continue  # a newer request arrived; go round again

            self._render_and_show(name, detail)

    def _render_and_show(self, name: str, detail: bool = False) -> None:
        app = self.registry[name]
        started = time.monotonic()
        try:
            log.info("rendering %s%s", name, " (detail)" if detail else "")
            if detail:
                img = app.render_detail(self.panel.width, self.panel.height)
            else:
                img = app.render(self.panel.width, self.panel.height)
        except Exception:
            log.exception("render failed for %s", name)
            img = layout.error_screen(
                self.panel.width, self.panel.height, name,
                traceback.format_exc(limit=3),
            )
        try:
            self.panel.show(img)
        except Exception:
            log.exception("panel update failed")
            return
        self.current = name
        self.current_detail = detail
        self.last_shown_at = time.monotonic()
        log.info("showed %s in %.1fs", name, time.monotonic() - started)
