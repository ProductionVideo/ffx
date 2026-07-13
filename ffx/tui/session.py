"""The seam between the imperative wizard flow and the Textual app.

The flow (ffx.__main__ and every operation's prompt()) runs unchanged in a
worker thread; anything that would have painted the terminal directly asks
here first. Every function is a no-op returning None/False when no app is
active, so the classic InquirerPy path needs no branching at the call sites
beyond "did the session take it?".
"""
from __future__ import annotations

import threading
from io import StringIO
from typing import TYPE_CHECKING, Any, Optional

from rich.console import Console, RenderableType
from rich.text import Text

from ffx.ui.theme import FFX_THEME

if TYPE_CHECKING:
    from ffx.tui.app import FFXApp

_app: Optional["FFXApp"] = None


def set_app(app: Optional["FFXApp"]) -> None:
    global _app
    _app = app


def get_app() -> Optional["FFXApp"]:
    return _app


def render_to_text(renderable: RenderableType, width: int = 80) -> Text:
    """Render through a throwaway ffx-themed console into styled Text.

    Textual widgets render with the app's own console, which doesn't know
    the ffx.* named styles - so anything built against FFX_THEME (tables,
    panels, markup strings) gets fully resolved to concrete styles here
    before a widget ever sees it.
    """
    buffer = Console(theme=FFX_THEME, width=width, force_terminal=True, file=StringIO())
    with buffer.capture() as capture:
        buffer.print(renderable)
    return Text.from_ansi(capture.get().rstrip("\n"))


def prompt(screen: Any) -> Any:
    """Show a modal prompt screen and block (worker thread) for its answer."""
    assert _app is not None
    return _app.call_from_thread(_app.push_screen_wait, screen)


def show_media(renderable: RenderableType) -> bool:
    if _app is None:
        return False
    _app.call_from_thread(_app.set_media_pane, render_to_text(renderable, width=44))
    return True


def show_pipeline(renderable: RenderableType) -> bool:
    if _app is None:
        return False
    _app.call_from_thread(_app.set_pipeline_pane, render_to_text(renderable, width=70))
    return True


class ProgressHandle:
    """One running ffmpeg's progress, as seen from the runner's thread."""

    def __init__(self, app: "FFXApp"):
        self._app = app
        self.cancel_event = threading.Event()

    def update(self, completed: float) -> None:
        self._app.call_from_thread(self._app.update_progress, completed)

    def close(self) -> None:
        self._app.call_from_thread(self._app.close_progress)


def progress_open(description: str, total: float) -> Optional[ProgressHandle]:
    """Start showing an encode's progress in the app; None when no app is
    active (the runner then falls back to its own rich Progress bar)."""
    if _app is None:
        return None
    handle = ProgressHandle(_app)
    _app.call_from_thread(_app.open_progress, description, total, handle)
    return handle
