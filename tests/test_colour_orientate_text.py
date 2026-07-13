from pathlib import Path

from ffx.models import HardwareCapabilities, MediaInfo, StreamInfo
from ffx.operations import colour as colour_op
from ffx.operations import orientate as orientate_op
from ffx.operations import text as text_op


def _media(duration=10.0) -> MediaInfo:
    return MediaInfo(
        path=Path("in.mp4"),
        format_name="mp4",
        format_long_name="MP4",
        duration=duration,
        size=1000,
        bit_rate=1000,
        streams=[StreamInfo(index=0, codec_type="video", codec_name="h264", width=1920, height=1080)],
    )


def test_orientate_rotate_90cw():
    op = orientate_op.build({"mode": "rotate", "angle": 90}, _media(), None)
    assert op.video_filter == ["transpose=1"]
    assert op.description == "Rotate 90°"


def test_orientate_rotate_90ccw():
    op = orientate_op.build({"mode": "rotate", "angle": -90}, _media(), None)
    assert op.video_filter == ["transpose=2"]


def test_orientate_rotate_180():
    op = orientate_op.build({"mode": "rotate", "angle": 180}, _media(), None)
    assert op.video_filter == ["transpose=1,transpose=1"]


def test_orientate_flip_horizontal():
    op = orientate_op.build({"mode": "flip", "axis": "horizontal"}, _media(), None)
    assert op.video_filter == ["hflip"]


def test_orientate_flip_vertical():
    op = orientate_op.build({"mode": "flip", "axis": "vertical"}, _media(), None)
    assert op.video_filter == ["vflip"]


def test_colour_bw():
    op = colour_op.build({"mode": "bw"}, _media(), None)
    assert op.video_filter == ["hue=s=0"]


def test_colour_adjust():
    params = {"mode": "adjust", "brightness": 0.1, "contrast": 1.2, "saturation": 1.4, "gamma": 0.9}
    op = colour_op.build(params, _media(), None)
    assert op.video_filter == ["eq=brightness=0.1:contrast=1.2:saturation=1.4:gamma=0.9"]


def test_colour_temperature():
    op = colour_op.build({"mode": "temperature", "kelvin": 4500}, _media(), None)
    assert op.video_filter == ["colortemperature=temperature=4500"]


def test_colour_vintage_is_a_filter_chain():
    op = colour_op.build({"mode": "vintage"}, _media(), None)
    assert len(op.video_filter) == 1
    assert "vignette" in op.video_filter[0]


def test_colour_lut_quotes_and_escapes_path():
    op = colour_op.build({"mode": "lut", "path": "/tmp/it's a lut.cube"}, _media(), None)
    assert op.video_filter == ["lut3d=file='/tmp/it\\'s a lut.cube'"]
    assert "it's a lut.cube" in op.description


def test_text_default_position_and_no_timing():
    op = text_op.build({"text": "Hello"}, _media(), None)
    assert op.video_filter == ["drawtext=text='Hello':fontsize=36:fontcolor=white:x=(w-text_w)/2:y=h-text_h-20"]


def test_text_with_box_and_timing():
    params = {"position": "top-left", "size": 24, "color": "yellow", "box": True, "text": "Hi", "start": 1.0, "end": 4.0}
    op = text_op.build(params, _media(), None)
    vf = op.video_filter[0]
    assert vf.startswith("drawtext=text='Hi':fontsize=24:fontcolor=yellow:x=20:y=20")
    assert "box=1:boxcolor=black@0.5:boxborderw=10" in vf
    assert "enable='between(t,1.0,4.0)'" in vf
    assert "from 1.0s to 4.0s" in op.description


def test_text_escapes_quotes_and_backslashes():
    op = text_op.build({"text": "it's a \\test"}, _media(), None)
    assert "text='it\\'s a \\\\test'" in op.video_filter[0]


def test_text_prompt_bails_out_when_drawtext_unavailable(monkeypatch):
    no_drawtext = HardwareCapabilities(videotoolbox_available=False, hw_encoders=set(), hw_decoders=set(), filters=set())
    assert text_op.prompt(_media(), no_drawtext) is None


def test_text_prompt_proceeds_when_drawtext_available(monkeypatch):
    has_drawtext = HardwareCapabilities(
        videotoolbox_available=False, hw_encoders=set(), hw_decoders=set(), filters={"drawtext"}
    )
    monkeypatch.setattr(text_op.prompts, "choose_preset", lambda *a, **k: text_op.PRESETS[0])
    monkeypatch.setattr(text_op.prompts, "ask_text", lambda *a, **k: "Hello")
    monkeypatch.setattr(text_op.prompts, "ask_confirm", lambda *a, **k: False)

    params = text_op.prompt(_media(), has_drawtext)

    assert params is not None
    assert params["text"] == "Hello"
