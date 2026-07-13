"""The full-screen ffx shell.

The existing imperative wizard (ffx.__main__._flow) runs unchanged in a
thread worker; prompts surface as modal screens (ffx.tui.screens), console
output lands in the activity log, and the media/pipeline panes update in
place as the flow reports them through ffx.tui.session.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, ProgressBar, RichLog, Static

from ffx.tui import session
from ffx.ui import theme


class _ConsoleRelay:
    """A file-like sink for the module-global rich console.

    While the app is live, theme.console writes here instead of the real
    terminal (which Textual owns). Claims to be a terminal so rich keeps
    emitting ANSI color, which the log re-parses into styled Text.
    Writes arrive from the flow's worker thread, hence call_from_thread.
    """

    def __init__(self, app: "FFXApp"):
        self._app = app
        self._buffer = ""

    def write(self, text: str) -> None:
        self._buffer += text
        if "\n" in self._buffer:
            chunk, _, self._buffer = self._buffer.rpartition("\n")
            self._app.call_from_thread(self._app.append_log, chunk)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True


class FFXApp(App):
    TITLE = "ffx"

    CSS = """
    #banner {
        height: 1;
        background: $surface;
        color: $text;
        text-style: bold;
        padding: 0 2;
    }
    #panes {
        height: auto;
        max-height: 40%;
    }
    #media-pane, #pipeline-pane {
        border: solid $accent 40%;
        padding: 0 1;
        height: auto;
        max-height: 100%;
    }
    #media-pane {
        width: 50;
    }
    #pipeline-pane {
        width: 1fr;
    }
    #log {
        border: solid $accent 40%;
        padding: 0 1;
    }
    #progress-row {
        display: none;
        height: 1;
        padding: 0 2;
    }
    #progress-row.active {
        display: block;
    }
    #progress-label {
        width: auto;
        margin-right: 2;
    }
    #progress {
        width: 1fr;
    }
    #progress Bar {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+x", "cancel_encode", "Cancel encode", show=False),
    ]

    def __init__(self, flow: Callable[[], None]):
        super().__init__()
        self._flow = flow
        self._saved_console_file = None
        self._saved_console_width = None
        self._progress_handle: Optional[session.ProgressHandle] = None
        self._progress_total: float = 0.0
        self._pending_drop: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Static("ffx — ffmpeg, for the simple", id="banner")
        with Horizontal(id="panes"):
            yield Static("No file picked yet.", id="media-pane")
            yield Static("Pipeline is empty.", id="pipeline-pane")
        yield RichLog(id="log", wrap=True, auto_scroll=True)
        with Horizontal(id="progress-row"):
            yield Static("", id="progress-label")
            yield ProgressBar(id="progress", show_eta=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#media-pane", Static).border_title = "Media"
        self.query_one("#pipeline-pane", Static).border_title = "Pipeline"
        self.query_one("#log", RichLog).border_title = "Activity"
        session.set_app(self)
        self._saved_console_file = theme.console.file
        self._saved_console_width = theme.console.width
        theme.console.file = _ConsoleRelay(self)
        theme.console.width = 100
        self.run_worker(self._run_flow, thread=True)

    def on_unmount(self) -> None:
        session.set_app(None)
        if self._saved_console_file is not None:
            theme.console.file = self._saved_console_file
            theme.console.width = self._saved_console_width

    def _run_flow(self) -> None:
        from ffx.tui.screens import SelectScreen

        while True:
            failed = False
            try:
                self._flow()
            except SystemExit as exc:
                if exc.code:
                    failed = True
            except Exception:
                import traceback

                self.call_from_thread(self.append_log, traceback.format_exc())
                failed = True

            message = (
                "That run hit trouble (details in the log) — what now?"
                if failed
                else "All done — what now?"
            )
            choice, _ = session.prompt(
                SelectScreen(
                    message,
                    [("Start another pipeline", "again"), ("Quit ffx", "quit")],
                    default="again",
                )
            )
            if choice != "again":
                self.call_from_thread(self.exit)
                return
            self.call_from_thread(self.reset_panes)

    # ---- called (via call_from_thread) by ffx.tui.session ----

    def append_log(self, ansi_text: str) -> None:
        log = self.query_one("#log", RichLog)
        for line in ansi_text.split("\n"):
            log.write(Text.from_ansi(line))

    def set_media_pane(self, content: Text) -> None:
        self.query_one("#media-pane", Static).update(content)

    def reset_panes(self) -> None:
        self.query_one("#media-pane", Static).update("No file picked yet.")
        self.query_one("#pipeline-pane", Static).update("Pipeline is empty.")

    def set_pipeline_pane(self, content: Text) -> None:
        self.query_one("#pipeline-pane", Static).update(content)

    def open_progress(self, description: str, total: float, handle: session.ProgressHandle) -> None:
        self._progress_handle = handle
        self._progress_total = total
        self.query_one("#progress-label", Static).update(f"{description}  (Ctrl+X to cancel)")
        bar = self.query_one("#progress", ProgressBar)
        bar.update(total=total if total > 0 else None, progress=0)
        self.query_one("#progress-row", Horizontal).add_class("active")

    def update_progress(self, completed: float) -> None:
        if self._progress_total > 0:
            self.query_one("#progress", ProgressBar).update(progress=completed)

    def close_progress(self) -> None:
        self._progress_handle = None
        self.query_one("#progress-row", Horizontal).remove_class("active")

    def action_cancel_encode(self) -> None:
        if self._progress_handle is not None:
            self._progress_handle.cancel_event.set()

    # ---- app-wide drag-and-drop ----

    def on_paste(self, event: events.Paste) -> None:
        """A file dropped anywhere on the window, any time.

        A drop reaches the app as a Paste that no focused Input consumed
        (a focused path box handles its own). If the text is a real path:
        route it into the path screen that's up, or remember it for the
        next path question and say so - instead of the drop dying
        silently because the "right" widget didn't have focus.
        """
        from ffx.tui.screens import PathScreen
        from ffx.ui.prompts import clean_path_input

        text = clean_path_input(event.text).strip()
        if not text or not Path(text).expanduser().exists():
            return
        event.stop()
        if isinstance(self.screen, PathScreen):
            box = self.screen.query_one(Input)
            box.value = text
            box.cursor_position = len(text)
            box.focus()
        else:
            self._pending_drop = text
            self.notify(
                f"Got {Path(text).name} — it'll be filled in at the next path question.",
                timeout=5,
            )

    def take_pending_drop(self, *, want_dir: bool) -> Optional[str]:
        """Hand a stashed drop to the path screen that can use it.

        An output-directory question only claims a dropped folder - a
        dropped media file stays stashed rather than being misfiled as
        the place to write results.
        """
        if self._pending_drop is None:
            return None
        if want_dir and not Path(self._pending_drop).expanduser().is_dir():
            return None
        value, self._pending_drop = self._pending_drop, None
        return value
