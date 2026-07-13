"""Textual UI tests: prompt screens, the prompts-module bridge, and a full
end-to-end run of the real wizard flow inside the app (needs ffmpeg, like
test_main_smoke).

No pytest-asyncio here - each test drives its own event loop with
asyncio.run(), matching the rest of the suite staying plain-sync.
"""
import asyncio
import subprocess

import pytest
from textual import events
from textual.app import App
from textual.widgets import Input, ProgressBar, RichLog

from ffx.tui import session
from ffx.tui.app import FFXApp
from ffx.tui.screens import ConfirmScreen, PathScreen, PromptScreen, SelectScreen, TextScreen
from ffx.ui import prompts
from ffx.ui.prompts import TimestampValidator, _validator_fn


class Harness(App):
    """Pushes one prompt screen and records what it dismissed with."""

    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self.result = None
        self.settled = False

    def on_mount(self) -> None:
        def record(value):
            self.result = value
            self.settled = True

        self.push_screen(self._screen, record)


def drive(screen, *presses, before=None):
    async def scenario():
        app = Harness(screen)
        async with app.run_test() as pilot:
            await pilot.pause()
            if before is not None:
                before(app)
            await pilot.press(*presses)
            await pilot.pause()
        return app.result

    return asyncio.run(scenario())


def test_select_screen_returns_chosen_value():
    screen = SelectScreen("Pick:", [("Alpha", "a"), ("Beta", "b"), ("Gamma", "c")])
    assert drive(screen, "down", "enter") == ("b", False)


def test_select_screen_starts_on_default():
    screen = SelectScreen("Pick:", [("Alpha", "a"), ("Beta", "b"), ("Gamma", "c")], default="c")
    assert drive(screen, "enter") == ("c", False)


def test_select_screen_escape_goes_back_only_when_enabled():
    backable = SelectScreen("Pick:", [("Alpha", "a")], back_enabled=True)
    assert drive(backable, "escape") == (None, True)

    stubborn = SelectScreen("Pick:", [("Alpha", "a")], back_enabled=False)
    assert drive(stubborn, "escape", "enter") == ("a", False)


def test_text_screen_submits_and_validates():
    def set_value(app):
        app.screen.query_one(Input).value = "0:1:30"

    screen = TextScreen("When?", validate=_validator_fn(TimestampValidator()))
    assert drive(screen, "enter", before=set_value) == ("0:1:30", False)


def test_text_screen_rejects_invalid_input():
    def set_value(app):
        app.screen.query_one(Input).value = "not a timestamp"

    screen = TextScreen("When?", validate=_validator_fn(TimestampValidator()))
    # Invalid submit keeps the screen up (result never recorded).
    assert drive(screen, "enter", before=set_value) is None


def test_confirm_screen_keys():
    assert drive(ConfirmScreen("Sure?", default=True), "enter") == (True, False)
    assert drive(ConfirmScreen("Sure?", default=True), "n") == (False, False)
    assert drive(ConfirmScreen("Sure?", default=False), "y") == (True, False)


def test_path_screen_cleans_dropped_path_and_previews(tmp_path):
    """A Finder drag arrives backslash-escaped; the box should show the
    real path immediately and dismiss with the escaped text still cleanable."""
    target = tmp_path / "My Movie.mp4"
    target.touch()
    escaped = str(target).replace(" ", "\\ ")

    async def scenario():
        app = Harness(PathScreen("Path:", must_exist=True))
        async with app.run_test() as pilot:
            await pilot.pause()
            box = app.screen.query_one(Input)
            box._on_paste(events.Paste(escaped))
            await pilot.pause()
            shown = box.value
            await pilot.press("enter")
            await pilot.pause()
        return shown, app.result

    shown, result = asyncio.run(scenario())
    assert shown == str(target)
    assert result == (str(target), False)


def test_path_screen_rejects_missing_path():
    def set_value(app):
        app.screen.query_one(Input).value = "/no/such/file.mp4"

    screen = PathScreen("Path:", must_exist=True)
    assert drive(screen, "enter", before=set_value) is None


def test_drop_anywhere_is_stashed_and_prefills_next_path_screen(tmp_path):
    """A file dropped while some other screen is up gets remembered and
    fills the next path question; a dropped media file is NOT claimed by
    an output-directory question (want_dir)."""
    clip = tmp_path / "dropped.mp4"
    clip.touch()

    async def scenario():
        app = FFXApp(lambda: None)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            # No path screen up: the drop lands on the base screen.
            app.on_paste(events.Paste(str(clip).replace(" ", "\\ ")))
            stashed = app._pending_drop
            # An output-dir question must not claim the dropped file...
            not_claimed = app.take_pending_drop(want_dir=True)
            # ...but an input question does.
            claimed = app.take_pending_drop(want_dir=False)
            drained = app.take_pending_drop(want_dir=False)
            return stashed, not_claimed, claimed, drained

    stashed, not_claimed, claimed, drained = asyncio.run(scenario())
    assert stashed == str(clip)
    assert not_claimed is None
    assert claimed == str(clip)
    assert drained is None


def test_drop_routes_into_open_path_screen_replacing_default(tmp_path):
    clip = tmp_path / "My Movie.mp4"
    clip.touch()

    async def scenario():
        app = FFXApp(lambda: None)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.push_screen(PathScreen("Path:", default="/somewhere/else", must_exist=True))
            await pilot.pause()
            app.on_paste(events.Paste(str(clip).replace(" ", "\\ ")))
            await pilot.pause()
            return app.screen.query_one(Input).value

    assert asyncio.run(scenario()) == str(clip)


def test_pending_drop_prefills_path_screen_on_mount(tmp_path):
    clip = tmp_path / "queued.mp4"
    clip.touch()

    async def scenario():
        app = FFXApp(lambda: None)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.on_paste(events.Paste(str(clip)))
            app.push_screen(PathScreen("Path:", must_exist=True))
            await pilot.pause()
            return app.screen.query_one(Input).value

    assert asyncio.run(scenario()) == str(clip)


def test_progress_bar_is_actually_visible():
    """Regression: the label used to take 1fr and shove the bar off-screen."""

    async def scenario():
        app = FFXApp(lambda: None)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            handle = session.ProgressHandle(app)
            app.open_progress("Encoding sample.mp4", 100.0, handle)
            app.update_progress(42.0)
            await pilot.pause()
            return app.query_one("#progress", ProgressBar).region

    bar_region = asyncio.run(scenario())
    assert bar_region.width >= 20
    assert bar_region.x + bar_region.width <= 100


def test_bridged_prompts_choose_inside_wizard_backs_out():
    """prompts.choose routed through the app: pick a value, then a second
    run where Escape backs out of the first question and run_wizard
    returns None - the same contract the InquirerPy path honours."""

    class FlowApp(App):
        def __init__(self):
            super().__init__()
            self.picked = None
            self.backed = "unset"

        def on_mount(self) -> None:
            session.set_app(self)
            self.run_worker(self.flow, thread=True)

        def flow(self) -> None:
            self.picked = prompts.run_wizard(prompts.choose, "First?", [("One", 1), ("Two", 2)])
            self.backed = prompts.run_wizard(prompts.choose, "Second?", [("One", 1)])
            self.call_from_thread(self.exit)

    async def scenario():
        app = FlowApp()
        try:
            async with app.run_test() as pilot:
                await _wait_for_screen(pilot, app)
                await pilot.press("down", "enter")
                await _wait_for_screen(pilot, app)
                await pilot.press("escape")
                await pilot.pause(0.2)
        finally:
            session.set_app(None)
        return app.picked, app.backed

    picked, backed = asyncio.run(scenario())
    assert picked == 2
    assert backed is None


async def _wait_for_screen(pilot, app, timeout: float = 8.0) -> None:
    """Wait until a prompt screen is up (the flow runs in a worker thread,
    so screens appear asynchronously between key presses)."""
    elapsed = 0.0
    while not isinstance(app.screen, PromptScreen):
        await pilot.pause(0.05)
        elapsed += 0.05
        if elapsed > timeout:
            raise AssertionError(f"No prompt screen appeared; current: {app.screen!r}")


async def _wait_for_message(pilot, app, fragment: str, timeout: float = 15.0) -> None:
    elapsed = 0.0
    while True:
        screen = app.screen
        if isinstance(screen, PromptScreen) and fragment in screen._message:
            return
        await pilot.pause(0.05)
        elapsed += 0.05
        if elapsed > timeout:
            current = screen._message if isinstance(screen, PromptScreen) else repr(screen)
            log = "\n".join(str(line) for line in app.query_one("#log", RichLog).lines)
            raise AssertionError(f"Never saw prompt {fragment!r}; current: {current}\nLog:\n{log}")


@pytest.fixture
def sample_clip(tmp_path):
    clip = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(clip),
        ],
        capture_output=True,
        check=True,
    )
    return clip


def test_full_flow_in_app_scale_preset(sample_clip, tmp_path):
    """The real wizard (_flow) inside the real app: pick the sample clip,
    queue Scale via its 'Half size' preset, run the encode, decline the
    recipe offer - then the output file exists at half resolution."""
    from ffx import hardware
    from ffx.__main__ import _flow

    caps = hardware.detect()
    app = FFXApp(lambda: _flow(caps))

    async def scenario():
        async with app.run_test(size=(100, 40)) as pilot:
            await _wait_for_message(pilot, app, "Path to a media file")
            app.screen.query_one(Input).value = str(sample_clip)
            await pilot.press("enter")

            await _wait_for_message(pilot, app, "What next?")
            await pilot.press("down", "down", "enter")  # convert, cut -> scale

            await _wait_for_message(pilot, app, "Scale — choose a preset")
            await pilot.press(*(["down"] * 5), "enter")  # -> Half size

            await _wait_for_message(pilot, app, "What next?")
            await pilot.press("enter")  # default is Done once the pipeline has an op

            await _wait_for_message(pilot, app, "Output directory")
            await pilot.press("enter")  # default: alongside the input

            await _wait_for_message(pilot, app, "Run it?")
            await pilot.press("enter")  # default Yes; encode runs for real here

            await _wait_for_message(pilot, app, "recipe")
            await pilot.press("enter")  # default No

            await _wait_for_message(pilot, app, "All done — what now?")
            await pilot.press("down", "enter")  # Quit ffx
            await pilot.pause(0.3)

    asyncio.run(scenario())

    out = tmp_path / "sample.scale.mp4"
    assert out.exists()
    probe_out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert probe_out == "160,120"
