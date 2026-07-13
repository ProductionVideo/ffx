"""The Filters catalogue - fragment construction and availability gating."""
from pathlib import Path

from ffx.models import HardwareCapabilities, MediaInfo, StreamInfo
from ffx.operations import filters

CAPS = HardwareCapabilities(videotoolbox_available=False, hw_encoders=set(), hw_decoders=set())


def _media(*, audio=True, duration=10.0) -> MediaInfo:
    streams = [StreamInfo(index=0, codec_type="video", codec_name="h264", width=1920, height=1080)]
    if audio:
        streams.append(StreamInfo(index=1, codec_type="audio", codec_name="aac"))
    return MediaInfo(
        path=Path("in.mp4"), format_name="mp4", format_long_name="",
        duration=duration, size=1000, bit_rate=5_000_000, streams=streams,
    )


def test_every_effect_builds_a_video_filter():
    for key in filters._EFFECTS:
        params = {"effect": key}
        op = filters.build(params, _media(), CAPS)
        assert op.video_filter, key
        assert op.description, key


def test_parameterized_effects_use_their_params():
    op = filters.build({"effect": "sharpen", "amount": 2.5}, _media(), CAPS)
    assert op.video_filter == ["unsharp=5:5:2.5"]
    op = filters.build({"effect": "pixelate", "block": 32}, _media(), CAPS)
    assert op.video_filter == ["pixelize=w=32:h=32"]
    op = filters.build({"effect": "aberration", "shift": 10}, _media(), CAPS)
    assert op.video_filter == ["chromashift=cbh=10:crh=-10"]


def test_fade_covers_both_ends_and_audio():
    op = filters.build({"effect": "fade", "fade_in": 1.0, "fade_out": 2.0}, _media(duration=10.0), CAPS)
    assert "fade=t=in:st=0:d=1.0" in op.video_filter
    assert "fade=t=out:st=8.000:d=2.0" in op.video_filter
    assert "afade=t=in:st=0:d=1.0" in op.audio_filter
    assert "afade=t=out:st=8.000:d=2.0" in op.audio_filter


def test_fade_skips_audio_when_source_is_silent():
    op = filters.build({"effect": "fade", "fade_in": 1.0, "fade_out": 1.0}, _media(audio=False), CAPS)
    assert op.audio_filter == []


def test_fade_out_dropped_when_longer_than_clip():
    op = filters.build({"effect": "fade", "fade_in": 0, "fade_out": 30.0}, _media(duration=10.0), CAPS)
    assert op.video_filter == []


def test_every_effect_declares_a_real_gate_filter():
    for key, effect in filters._EFFECTS.items():
        assert effect["filter"], key
