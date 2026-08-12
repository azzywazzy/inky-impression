"""The four buttons on the edge of the Inky Impression.

Uses gpiod rather than gpiozero. That's deliberate: Pimoroni ported the Inky
library and its examples to gpiod for Bookworm and later, and gpiozero's older
pin factories can fail to see edges on recent Raspberry Pi OS releases without
raising anything - the buttons simply do nothing. gpiod is also already
installed, since the inky package depends on it.

Pins are BCM GPIO numbers, matching Pimoroni's examples/7color/buttons.py.
(On the 13.3" board button C is GPIO 25 rather than 16 - not your problem on
a 5.7", but worth knowing.)

Run this module directly to test the buttons on their own:

    python -m inkyapps.buttons
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

import gpiod
import gpiodevice
from gpiod.line import Bias, Direction, Edge, Value

log = logging.getLogger(__name__)

BUTTON_PINS = {"A": 5, "B": 6, "C": 16, "D": 24}

DEBOUNCE_S = 0.25
HOLD_S = 5.0

# The buttons pull to ground, so we want a pull-up and a falling edge.
_SETTINGS = gpiod.LineSettings(
    direction=Direction.INPUT,
    bias=Bias.PULL_UP,
    edge_detection=Edge.FALLING,
)


class ButtonPad(threading.Thread):
    def __init__(self, mapping: dict, on_press, on_detail=None,
                 detail_letter: str = "", hold_d_to_shutdown: bool = False):
        """mapping: {"A": "apod", ...}. Values of None are ignored.

        All four lines are watched even when unmapped, so an unexpected press
        gets logged rather than vanishing - which makes "nothing happens when
        I press B" much easier to diagnose.
        """
        super().__init__(daemon=True, name="buttons")
        self.mapping = mapping
        self.on_press = on_press
        self.on_detail = on_detail
        self.detail_letter = (detail_letter or "").upper()
        self.hold_d_to_shutdown = hold_d_to_shutdown
        self._last_press: dict[str, float] = {}
        # NB: don't name anything on a Thread subclass _handle, _target,
        # _args, _kwargs, _name or _started - threading.Thread sets those as
        # instance attributes, which silently shadow same-named methods.

        chip = gpiodevice.find_chip_by_platform()
        self._offsets = {}
        for letter, pin in BUTTON_PINS.items():
            self._offsets[chip.line_offset_from_id(pin)] = letter

        self._request = chip.request_lines(
            consumer="inky-apps",
            config=dict.fromkeys(self._offsets, _SETTINGS),
        )
        log.info("watching buttons: %s",
                 ", ".join(f"{k}=GPIO{v}" for k, v in BUTTON_PINS.items()))
        if self.detail_letter and self.on_detail:
            log.info("button %s shows more detail for the current app",
                     self.detail_letter)
        self.start()

    def run(self) -> None:
        while True:
            try:
                for event in self._request.read_edge_events():
                    self._dispatch(self._offsets.get(event.line_offset))
            except Exception:
                log.exception("button read failed")
                time.sleep(1)

    def _dispatch(self, letter: str | None) -> None:
        if letter is None:
            return

        # Checked before debouncing: a genuine hold takes a real 5 seconds, so
        # it can never be mistaken for mechanical bounce. Gating it behind the
        # debounce window like every other press meant a hold started soon
        # after an earlier tap (e.g. tap D, tap D, hold D in quick succession)
        # got silently dropped here before it was ever evaluated - shutdown
        # would then not trigger no matter how long the button stayed down.
        if letter == "D" and self.hold_d_to_shutdown and self._still_held("D"):
            log.warning("button D held - shutting down")
            subprocess.run(["sudo", "poweroff"], check=False)
            return

        now = time.monotonic()
        if now - self._last_press.get(letter, 0.0) < DEBOUNCE_S:
            return
        self._last_press[letter] = now

        if letter == self.detail_letter and self.on_detail:
            log.info("button %s pressed -> detail view", letter)
            self.on_detail()
            return

        app_name = self.mapping.get(letter)
        log.info("button %s pressed -> %s", letter, app_name or "(not mapped)")
        if app_name:
            self.on_press(app_name)

    def _still_held(self, letter: str) -> bool:
        """Poll the line to see if it stayed down for HOLD_S seconds."""
        offset = next(o for o, l in self._offsets.items() if l == letter)
        deadline = time.monotonic() + HOLD_S
        while time.monotonic() < deadline:
            # Pull-up: inactive/high means the button has been released.
            if self._request.get_value(offset) == Value.ACTIVE:
                return False
            time.sleep(0.2)
        return True


def _selftest() -> None:
    """python -m inkyapps.buttons - print presses, nothing else."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("Press buttons A-D. Ctrl-C to stop.\n")
    ButtonPad({"A": "a", "B": "b", "C": "c", "D": "d"},
              lambda name: print(f"  -> would launch: {name}"))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    _selftest()
