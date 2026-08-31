from pathlib import Path

from ffx import dimensions
from ffx.models import MediaInfo, StreamInfo


def _media(width=1920, height=1080) -> MediaInfo:
    video = StreamInfo(index=0, codec_type="video", codec_name="h264", width=width, height=height)
    return MediaInfo(
        path=Path("in.mp4"), format_name="mp4", format_long_name="",
        duration=10.0, size=1000, bit_rate=5000, streams=[video],
    )


def _op(name, **params):
    class _Module:
        pass

    m = _Module()
    m.name = name
    return (m, params)


def test_no_ops_returns_source_size():
    assert dimensions.effective_size(_media(), []) == (1920, 1080)


def test_scale_by_width_keeps_aspect_and_rounds_even():
    size = dimensions.effective_size(_media(1920, 1080), [_op("scale", mode="width", width=1281)])
    # 1080 * 1281 / 1920 = 720.5625 -> rounds to nearest even -> 720
    assert size == (1281, 720)


def test_scale_by_height_keeps_aspect():
    size = dimensions.effective_size(_media(1920, 1080), [_op("scale", mode="height", height=540)])
    assert size == (960, 540)


def test_scale_by_percent():
    size = dimensions.effective_size(_media(1920, 1080), [_op("scale", mode="percent", percent=50)])
    assert size == (960, 540)


def test_scale_fit_fill_stretch_land_on_exact_canvas():
    for mode in ("fit", "fill", "stretch"):
        size = dimensions.effective_size(
            _media(1920, 1080), [_op("scale", mode=mode, width=800, height=800)]
        )
        assert size == (800, 800)


def test_crop_rect_is_the_exact_requested_rectangle():
    size = dimensions.effective_size(
        _media(1920, 1080), [_op("crop", mode="rect", width=1000, height=500, x=0, y=0)]
    )
    assert size == (1000, 500)


def test_crop_aspect_matches_aspect_crop_filter_math():
    # Source wider than target -> crop width, keep height (mirrors
    # crop.py's _aspect_crop_filter exactly).
    size = dimensions.effective_size(_media(1920, 1080), [_op("crop", mode="aspect", aspect="1:1")])
    assert size == (1080, 1080)

    # Source narrower than target -> crop height, keep width.
    size = dimensions.effective_size(_media(1080, 1920), [_op("crop", mode="aspect", aspect="16:9")])
    assert size == (1080, 608)


def test_crop_border_adds_thickness_both_sides():
    size = dimensions.effective_size(_media(1920, 1080), [_op("crop", mode="border", thickness=20)])
    assert size == (1960, 1120)


def test_orientate_90_and_270_swap_dimensions():
    for angle in (90, -90):
        size = dimensions.effective_size(
            _media(1920, 1080), [_op("orientate", mode="rotate", angle=angle)]
        )
        assert size == (1080, 1920)


def test_orientate_180_and_flip_do_not_change_dimensions():
    size = dimensions.effective_size(_media(1920, 1080), [_op("orientate", mode="rotate", angle=180)])
    assert size == (1920, 1080)
    size = dimensions.effective_size(_media(1920, 1080), [_op("orientate", mode="flip", axis="horizontal")])
    assert size == (1920, 1080)


def test_operations_that_do_not_affect_size_are_ignored():
    size = dimensions.effective_size(
        _media(1920, 1080),
        [_op("colour", brightness=10), _op("text", text="hi"), _op("timecode", mode="set")],
    )
    assert size == (1920, 1080)


def test_chained_scale_then_crop_matches_the_reported_failure_scenario():
    # The exact sequence that failed against real ffmpeg while building
    # this fix: scale to 1280 wide, then a manual crop rectangle sized
    # for the *original* 1920x1080 frame no longer fits.
    ops = [_op("scale", mode="width", width=1280)]
    size = dimensions.effective_size(_media(1920, 1080), ops)
    assert size == (1280, 720)  # this, not 1920x1080, is what Crop must be bounded against


def test_effective_media_preserves_everything_else():
    audio = StreamInfo(index=1, codec_type="audio", codec_name="aac", channels=2)
    media = _media()
    media.streams.append(audio)
    media.tags = {"title": "x"}

    result = dimensions.effective_media(media, [_op("scale", mode="width", width=1280)])
    assert result.primary_video.width == 1280
    assert result.primary_video.height == 720
    assert result.primary_audio is audio  # untouched, same object
    assert result.tags == {"title": "x"}
    assert result.duration == media.duration
    assert result.path == media.path
    # The original media object itself is never mutated.
    assert media.primary_video.width == 1920


def test_effective_media_returns_the_same_object_when_nothing_changes_size():
    media = _media()
    assert dimensions.effective_media(media, [_op("colour", brightness=10)]) is media


def test_effective_size_none_without_a_video_stream():
    audio_only = MediaInfo(
        path=Path("in.mp3"), format_name="mp3", format_long_name="",
        duration=10.0, size=1000, bit_rate=5000,
        streams=[StreamInfo(index=0, codec_type="audio", codec_name="mp3")],
    )
    assert dimensions.effective_size(audio_only, []) is None
    assert dimensions.effective_media(audio_only, []) is audio_only
