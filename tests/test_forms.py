"""The single-screen Convert form - live dependencies and params parity
with what the sequential prompt() flow would produce."""
import asyncio
from pathlib import Path

from textual.app import App
from textual.widgets import Select

from ffx.models import HardwareCapabilities, MediaInfo, StreamInfo
from ffx.tui.forms import ConvertScreen

NO_HW = HardwareCapabilities(
    videotoolbox_available=False, hw_encoders=set(), hw_decoders=set(), encoders={"libx264"}
)
WITH_HAP = HardwareCapabilities(
    videotoolbox_available=False, hw_encoders=set(), hw_decoders=set(), encoders={"hap", "libx264"}
)


def _media() -> MediaInfo:
    video = StreamInfo(index=0, codec_type="video", codec_name="h264", width=1920, height=1080,
                       bit_rate=5_000_000)
    audio = StreamInfo(index=1, codec_type="audio", codec_name="aac", bit_rate=192_000)
    return MediaInfo(
        path=Path("in.mp4"), format_name="mp4", format_long_name="",
        duration=60.0, size=40_000_000, bit_rate=5_192_000, streams=[video, audio],
    )


class Harness(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen
        self.result = None

    def on_mount(self) -> None:
        def record(value):
            self.result = value

        self.push_screen(self._screen, record)


def drive(caps=NO_HW, setup=None):
    async def scenario():
        app = Harness(ConvertScreen(_media(), caps))
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            if setup is not None:
                setup(app.screen)
                await pilot.pause()
            await pilot.click("#add")
            await pilot.pause()
        return app.result

    return asyncio.run(scenario())


def test_defaults_produce_balanced_bitrate_params():
    params, back = drive()
    assert back is False
    assert params["vcodec"] == "h264"
    assert params["container"] == "mp4"
    assert params["acodec"] == "copy"
    assert params["engine"] == "software"
    assert params["quality_mode"] == "bitrate"
    assert params["video_kbps"] > 0


def test_copy_codec_needs_no_quality():
    def pick_copy(screen):
        screen.query_one("#codec", Select).value = "copy_v"

    params, _ = drive(setup=pick_copy)
    assert params == {"container": "mp4", "vcodec": "copy_v", "acodec": "copy"}


def test_codec_change_refilters_containers():
    def pick_prores(screen):
        screen.query_one("#codec", Select).value = "prores"

    params, _ = drive(setup=pick_prores)
    assert params["container"] == "mov"
    assert params["acodec"] == "pcm"
    assert params["prores_profile"] == "3"
    assert params["engine"] == "software"


def test_keyboard_only_flow_arrow_cycles_and_ctrl_s_submits():
    """No mouse, no dropdowns: → on the focused codec Select steps its
    value in place, Ctrl+S submits from anywhere."""

    async def scenario():
        app = Harness(ConvertScreen(_media(), NO_HW))
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen.focused, Select)
            await pilot.press("right")  # h264 -> hevc
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
        return app.result

    params, back = asyncio.run(scenario())
    assert back is False
    assert params["vcodec"] == "hevc"
    assert params["quality_mode"] == "bitrate"


def test_left_arrow_wraps_backwards():
    async def scenario():
        app = Harness(ConvertScreen(_media(), NO_HW))
        async with app.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            await pilot.press("left")  # h264 wraps to the last codec entry
            await pilot.pause()
            await pilot.press("ctrl+s")
            await pilot.pause()
        return app.result

    params, _ = asyncio.run(scenario())
    assert params["vcodec"] == "copy_v"


def test_hap_offered_only_when_encoder_exists():
    def read_options(screen):
        values = {value for _, value in screen.query_one("#codec", Select)._options}
        read_options.values = values

    drive(caps=NO_HW, setup=read_options)
    assert "hap" not in read_options.values

    drive(caps=WITH_HAP, setup=read_options)
    assert "hap" in read_options.values
