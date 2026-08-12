"""The contract every mini-app implements."""

from __future__ import annotations

from PIL import Image


class App:
    #: short identifier, used in config.BUTTON_APPS and the URL in serve.py
    name: str = "app"

    #: shown in the header bar
    title: str = "App"

    #: does this app have a second "more detail" view, reachable with the
    #: detail button? If True, implement render_detail().
    has_detail: bool = False

    #: draw the A-D legend down the edge? Photo apps usually want the whole
    #: panel, so they set this False and get the full canvas to fill.
    show_buttons: bool = True

    #: re-render automatically every N minutes while this app is on screen.
    #: None means "only redraw when a button is pressed".
    refresh_minutes: int | None = None

    def render_detail(self, w: int, h: int):
        """Optional second view, shown when the detail button is pressed.

        Only called when has_detail is True. Pressing the button again goes
        back to the main view.
        """
        raise NotImplementedError

    def start(self) -> None:
        """Called once at startup by run.py, before any rendering.

        Use it to kick off background work - a poller that needs to have been
        running before the user presses the button, for instance. Not called
        by preview.py, so previews never start network threads.
        """

    def render(self, w: int, h: int) -> Image.Image:
        """Return a w x h image. Mode "P" (palette indices) for UI screens,
        mode "RGB" for photos you want dithered.

        Do all your network I/O here. Exceptions are caught by the refresh
        worker and turned into an on-screen error card, so don't swallow them
        silently - let them propagate if you can't produce a sensible screen.
        """
        raise NotImplementedError
