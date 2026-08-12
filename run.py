#!/usr/bin/env python3
"""Entry point. Run under systemd; see inkyapps.service."""

from __future__ import annotations

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

    # Let apps kick off background work (the aircraft tracker, for one)
    # before anyone presses a button.
    for name, app in REGISTRY.items():
        try:
            app.start()
        except Exception:
            log.exception("app %s failed to start", name)

    if config.STARTUP_APP:
        worker.request(config.STARTUP_APP)
    log.info("running - apps: %s", ", ".join(sorted(REGISTRY)))
    log.info("buttons: %s", mapping or "none mapped!")

    # Auto-refresh whatever is currently on screen, if that app wants it.
    while not stopping:
        time.sleep(SCHEDULER_TICK_S)
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
