"""Textual UI tests: prompt screens, the prompts-module bridge, and a full
end-to-end run of the real wizard flow inside the app (needs ffmpeg, like
test_main_smoke).

No pytest-asyncio here - each test drives its own event loop with
asyncio.run(), matching the rest of the suite staying plain-sync.
"""
import asyncio
import subprocess

import pytest
from rich.text import Text
from textual import events
from textual.app import App
from textual.widgets import Input, ProgressBar, RichLog, Static

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


def test_ctrl_b_f_scroll_the_log_behind_an_open_modal():
    """Regression: once a modal (the operations menu, a QC report) has
    pushed the log's newest lines past the fold, a ModalScreen owns all
    input - the log itself never sees a key while something is on top of
    it. Ctrl+B/Ctrl+F (the vi/less pager convention) are bound on the App
    so they intercept before dispatch reaches the active screen, and
    should scroll the log even while a totally unrelated modal is
    focused and answering keys."""

    async def scenario():
        app = FFXApp(lambda: None)
        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            log = app.query_one("#log", RichLog)
            for i in range(200):
                log.write(f"line {i}")
            await pilot.pause()
            top_before_scroll = log.scroll_y

            # A modal is up and focused - the log is not the active
            # screen's widget, so it can't receive keys directly.
            app.push_screen(SelectScreen("What next?", [("Convert", "convert"), ("Cut", "cut")]))
            await pilot.pause()
            assert isinstance(app.screen, SelectScreen)

            await pilot.press("ctrl+b")
            await pilot.pause()
            scrolled_up = log.scroll_y

            await pilot.press("ctrl+f")
            await pilot.pause()
            scrolled_down = log.scroll_y

            # The modal never lost focus/functioned normally throughout.
            still_modal = isinstance(app.screen, SelectScreen)
            return top_before_scroll, scrolled_up, scrolled_down, still_modal

    top_before, scrolled_up, scrolled_down, still_modal = asyncio.run(scenario())
    assert scrolled_up < top_before
    assert scrolled_down > scrolled_up
    assert still_modal is True


def test_ctrl_r_clears_chrome_and_dismisses_the_open_screen():
    """Regression target: Ctrl+R should wipe the log/panes and unblock
    whatever prompt is currently up, however deep in the flow it is -
    exercised here directly via action_reset_session rather than through
    a real flow, to isolate the chrome-clearing/dismiss mechanics from
    the exception-propagation behaviour covered separately below."""

    async def scenario():
        app = FFXApp(lambda: None)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            log = app.query_one("#log", RichLog)
            log.write("leftover output")
            app.set_media_pane(Text("sample.mp4"))
            app.set_pipeline_pane(Text("1. Scale"))
            await pilot.pause()

            screen = SelectScreen("Some question", [("A", "a"), ("B", "b")])
            dismissed = {}
            app.push_screen(screen, lambda value: dismissed.setdefault("result", value))
            await pilot.pause()
            assert app.screen is screen

            app.action_reset_session()
            await pilot.pause()

            return (
                dismissed.get("result"),
                len(log.lines),
                str(app.query_one("#media-pane", Static).content),
                str(app.query_one("#pipeline-pane", Static).content),
            )

    result, log_lines, media_text, pipeline_text = asyncio.run(scenario())
    assert result == session.RESET
    assert log_lines == 0
    assert media_text == "No file picked yet."
    assert pipeline_text == "Pipeline is empty."


def test_ctrl_r_key_binding_fires_through_a_modal():
    """The actual key path (not calling the action directly): Ctrl+R
    while a modal is up should reach the App exactly like Ctrl+B/Ctrl+F
    do - same priority-binding mechanism, verified the same way."""

    async def scenario():
        app = FFXApp(lambda: None)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            app.query_one("#log", RichLog).write("some output")
            screen = SelectScreen("Some question", [("A", "a")])
            app.push_screen(screen)
            await pilot.pause()

            await pilot.press("ctrl+r")
            await pilot.pause()

            return isinstance(app.screen, SelectScreen), len(app.query_one("#log", RichLog).lines)

    still_modal_but_different, log_lines = asyncio.run(scenario())
    # A *new* prompt (the flow's next question, or here just nothing since
    # the fake flow is a no-op) may or may not be up - what matters is the
    # log got cleared, proving the key reached action_reset_session at all.
    assert log_lines == 0


def test_reset_requested_propagates_through_flow_instead_of_being_logged_as_a_failure():
    """Regression: _run_flow_once's generic `except Exception` used to
    catch ResetRequested too (it IS an Exception), silently treating a
    reset as a crashed run - logging a traceback and showing the 'hit
    trouble' message - instead of letting FlowApp's own handler restart
    cleanly. A fake flow that raises ResetRequested on its second call
    (simulating a reset landing mid-question) must NOT produce a
    traceback in the log, and _run_flow must loop back into the flow
    again rather than stopping."""

    async def scenario():
        calls = []

        def fake_flow():
            calls.append(1)
            if len(calls) == 1:
                return  # first pass: finishes normally
            if len(calls) == 2:
                raise session.ResetRequested()  # simulates a reset mid-question
            return  # third pass: let the app settle so cleanup doesn't hang

        app = FFXApp(fake_flow)
        async with app.run_test(size=(100, 30)) as pilot:
            await _wait_for_screen(pilot, app)  # "All done - what now?"
            app.action_reset_session()  # reset while that prompt is up
            await pilot.pause(0.3)
            await _wait_for_screen(pilot, app)  # back to "All done" from pass 3
            log_text = "\n".join(str(line) for line in app.query_one("#log", RichLog).lines)
            return calls, log_text

    calls, log_text = asyncio.run(scenario())
    assert len(calls) == 3
    assert "Traceback" not in log_text


def test_big_menu_leaves_most_of_the_log_visible():
    """Regression: a long menu (the 17-category operations list, here
    stood in for by 20 generic items) used to grow tall enough to cover
    nearly the entire log behind it - only ~11 of 35 log rows stayed
    visible on a 40-row terminal. The list's own scroll cap is now
    viewport-relative, so most of the log stays uncovered regardless of
    terminal size."""

    async def scenario():
        app = FFXApp(lambda: None)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            log = app.query_one("#log", RichLog)
            for i in range(60):
                log.write(f"line {i}")
            await pilot.pause()

            choices = [(f"Item {i}", i) for i in range(20)]
            app.push_screen(SelectScreen("What next?", choices))
            await pilot.pause()

            vertical = app.screen.query_one("Vertical")
            return log.region, vertical.region

    log_region, modal_region = asyncio.run(scenario())
    covered = max(0, (log_region.y + log_region.height) - max(log_region.y, modal_region.y))
    visible = log_region.height - covered
    # Was 11/35 (~31%) before this fix; require comfortably better.
    assert visible >= log_region.height * 0.4


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

        def take_reset_pending(self) -> bool:
            # Minimal double standing in for FFXApp - this test isn't
            # exercising reset, but session.prompt() unconditionally
            # checks this on whatever _app is set, so it needs to exist.
            return False

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


def test_ctrl_r_returns_the_real_flow_to_step_one(sample_clip):
    """End to end with the real _flow (no fakes): get partway into a real
    pipeline - a file picked, an operation queued, sitting at the
    operations menu (step 2/4) - then Ctrl+R. The flow must land back on
    the very first question, with the log and Media pane wiped, not just
    resume from wherever it was."""
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

            # Now sitting at the operations menu with a real queued op and
            # a real populated Media/Pipeline pane and log history behind it.
            await _wait_for_message(pilot, app, "What next?")
            media_before = str(app.query_one("#media-pane", Static).content)
            assert sample_clip.name in media_before

            await pilot.press("ctrl+r")
            await pilot.pause(0.3)

            # Back to the very first question - not resumed mid-pipeline.
            await _wait_for_message(pilot, app, "Path to a media file")
            media_after = str(app.query_one("#media-pane", Static).content)
            log_text_after = "\n".join(str(line) for line in app.query_one("#log", RichLog).lines)
            return media_after, log_text_after

    media_after, log_text_after = asyncio.run(scenario())
    assert media_after == "No file picked yet."
    # The log was cleared, not just added to - it holds only the fresh
    # restart's own output (its "1/4" step banner), never the "2/4" step
    # marker or anything else from the pipeline that was abandoned.
    assert "1/4" in log_text_after
    assert "2/4" not in log_text_after


def test_analyse_declining_the_pipeline_gate_restarts_with_a_new_file(sample_clip):
    """End to end with the real _flow: run Analyse, answer 'n' to 'Back
    to the pipeline?' - must land back on the very first question with a
    fresh Media pane AND a wiped log (not just resumed), not silently
    continue to the operations menu the way 'y' would (that used to be
    indistinguishable from 'n'), and not leave the QC report it declined
    still sitting in the log either (that was the next thing reported
    broken - reset_panes() covered the panes but nothing cleared the log
    on this specific path)."""
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
            await pilot.press("a", "enter")  # type-to-jump -> Analyse

            await _wait_for_message(pilot, app, "choose a report")
            await pilot.press("enter")  # Full QC report preset

            await _wait_for_message(pilot, app, "Back to the pipeline?")
            await pilot.press("n")

            # Restarted, not "What next?" again with the same file.
            await _wait_for_message(pilot, app, "Path to a media file")
            media_after = str(app.query_one("#media-pane", Static).content)
            log_text_after = "\n".join(str(line) for line in app.query_one("#log", RichLog).lines)
            return media_after, log_text_after

    media_after, log_text_after = asyncio.run(scenario())
    assert media_after == "No file picked yet."
    # Only the fresh restart's own "1/4" banner - none of the declined
    # run's QC report (streams table, frame data, etc.) still lingering.
    assert "1/4" in log_text_after
    assert "Streams" not in log_text_after
    assert "Frame data" not in log_text_after


def test_analyse_frame_data_against_real_ffmpeg(sample_clip):
    """End to end with the real _flow and real ffmpeg: run Analyse with
    the Frame data check, verify the rendered report actually shows
    frame-level numbers (not just that nothing crashed) - a real 30fps
    clip's report should say so, and log a real frame count."""
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
            await pilot.press("a", "enter")  # type-to-jump -> Analyse

            await _wait_for_message(pilot, app, "choose a report")
            # Custom -> just "frames" (skip the multi-select's other
            # defaults so this test isn't also waiting on black/silence
            # scans it doesn't care about).
            await pilot.press("down", "enter")

            await _wait_for_message(pilot, app, "Which checks?")
            # Toggle off the pre-checked defaults (streams, frames,
            # black, silence in that order) except "frames".
            await pilot.press("space", "down", "down", "space", "down", "space")
            await pilot.press("enter")

            await _wait_for_message(pilot, app, "Back to the pipeline?")
            log_text = "\n".join(str(line) for line in app.query_one("#log", RichLog).lines)
            return log_text

    log_text = asyncio.run(scenario())
    assert "Frame data" in log_text
    assert "Total frames" in log_text
    assert "30" in log_text  # the sample clip is encoded at 30fps, 30 frames
