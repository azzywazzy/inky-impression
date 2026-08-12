#!/usr/bin/env python3
"""Entry point. Run under systemd; see inkyapps.service."""

from __future__ import annotations

import datetime
import logging
import signal
import sys
import time

import config
from inkyapps.apps import REGISTRY
from inkyapps.buttons import ButtonPad
from inkyapps.display import Panel, RefreshWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("inkyapps")

SCHEDULER_TICK_S = 20


def _morning_time() -> datetime.time | None:
    """Parsed once; None (with a warning) if MORNING_APP is set but the time
    string is malformed, so a typo doesn't just silently never fire."""
    if not config.MORNING_APP:
        return None
    try:
        hour, minute = (int(p) for p in config.MORNING_TIME.split(":"))
        return datetime.time(hour, minute)
    except (ValueError, AttributeError):
        log.warning("MORNING_TIME %r is not a valid \"HH:MM\" - morning "
                   "refresh disabled", config.MORNING_TIME)
        return None


def main() -> int:
    panel = Panel(saturation=config.SATURATION)
    worker = RefreshWorker(panel, REGISTRY,
                           min_interval_s=config.MIN_REFRESH_INTERVAL_S)
    worker.start()

    mapping = {k: v for k, v in config.BUTTON_APPS.items() if v}
    ButtonPad(mapping, worker.request,
              on_detail=worker.request_detail,
              detail_letter=config.DETAIL_BUTTON,
              hold_d_to_shutdown=config.HOLD_D_TO_SHUTDOWN)

    stopping = False

    def handle_signal(_signum, _frame):
        nonlocal stopping
        stopping = True
        worker.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Let apps kick off background work before anyone presses a button.
    for name, app in REGISTRY.items():
        try:
            app.start()
        except Exception:
            log.exception("app %s failed to start", name)

    if config.STARTUP_APP:
        worker.request(config.STARTUP_APP)
    log.info("running - apps: %s", ", ".join(sorted(REGISTRY)))
    log.info("buttons: %s", mapping or "none mapped!")

    morning_time = _morning_time()
    morning_done_on: datetime.date | None = None
    if morning_time:
        log.info("morning refresh: %s at %s", config.MORNING_APP,
                 config.MORNING_TIME)

    # Auto-refresh whatever is currently on screen, if that app wants it -
    # plus the once-a-day switch to MORNING_APP, whatever's on screen.
    while not stopping:
        time.sleep(SCHEDULER_TICK_S)
        now = datetime.datetime.now()

        if (morning_time and now.time() >= morning_time
                and morning_done_on != now.date()):
            log.info("morning refresh: switching to %s", config.MORNING_APP)
            worker.request(config.MORNING_APP)
            morning_done_on = now.date()

        name = worker.current
        if not name:
            continue
        every = REGISTRY[name].refresh_minutes
        if not every:
            continue
        if time.monotonic() - worker.last_shown_at >= every * 60:
            log.info("scheduled refresh of %s", name)
            worker.request(name, worker.current_detail)

    log.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
