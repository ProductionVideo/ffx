from pathlib import Path

from ffx import dimensions
from ffx.models import MediaInfo, StreamInfo
from ffx.operations import crop as crop_op
from ffx.operations import scale as scale_op
from ffx.operations import sound as sound_op
from ffx.operations.sound import output_extension
from ffx.operations.time import _atempo_chain
from ffx.ui import prompts


def _media(*, video=True, audio_count=1, duration=10.0) -> MediaInfo:
    streams = []
    if video:
        streams.append(StreamInfo(index=0, codec_type="video", codec_name="h264", width=1920, height=1080))
    for i in range(audio_count):
        streams.append(
            StreamInfo(
                index=len(streams),
                codec_type="audio",
                codec_name="aac",
                channels=2,
                tags={"language": "eng"} if i == 0 else {},
            )
        )
    return MediaInfo(
        path=Path("in.mp4"), format_name="mp4", format_long_name="MP4",
        duration=duration, size=1000, bit_rate=1000, streams=streams,
    )


def test_channels_left_to_stereo_is_unity_gain_duplicate():
    # Both output channels set from one input channel in a single pan
    # filter (coefficient 1) - not the mono-isolate-then-upmix path,
    # which goes through ffmpeg's default upmix matrix and attenuates
    # by ~3dB instead of duplicating at full level (verified against
    # real decoded audio while building this).
    op = sound_op._build_channels({"action": "left_to_stereo"})
    assert op.audio_filter == ["pan=stereo|c0=c0|c1=c0"]


def test_channels_right_to_stereo_is_unity_gain_duplicate():
    op = sound_op._build_channels({"action": "right_to_stereo"})
    assert op.audio_filter == ["pan=stereo|c0=c1|c1=c1"]


def test_channels_left_right_only_still_downmix_to_mono():
    # The pre-existing "isolate" actions are a different, still-useful
    # thing (true mono output) - left_to_stereo/right_to_stereo are
    # additive, not a replacement.
    assert sound_op._build_channels({"action": "left"}).audio_filter == ["pan=mono|c0=c0"]
    assert sound_op._build_channels({"action": "right"}).audio_filter == ["pan=mono|c0=c1"]


def _product(stages: list[str]) -> float:
    product = 1.0
    for stage in stages:
        product *= float(stage.split("=")[1])
    return product


def test_atempo_chain_within_native_range_is_single_stage():
    stages = _atempo_chain(1.5)
    assert stages == ["atempo=1.5"]


def test_atempo_chain_decomposes_large_factors():
    for factor in (3.0, 4.0, 8.0, 20.0, 0.25, 0.1):
        stages = _atempo_chain(factor)
        assert all(0.5 <= float(s.split("=")[1]) <= 2.0 for s in stages)
        assert abs(_product(stages) - factor) < 1e-6


def test_sound_output_extension_only_set_for_extract():
    assert output_extension({"mode": "extract", "codec": "mp3"}) == "mp3"
    assert output_extension({"mode": "mute"}) is None
    assert output_extension({"mode": "volume", "method": "gain", "gain_db": 0}) is None


def test_sound_delay_positive_uses_adelay():
    op = sound_op.build({"mode": "delay", "delay_ms": 250}, _media(), None)
    assert op.audio_filter == ["adelay=delays=250:all=1"]


def test_sound_delay_negative_trims_start():
    op = sound_op.build({"mode": "delay", "delay_ms": -250}, _media(), None)
    assert op.audio_filter == ["atrim=start=0.25", "asetpts=PTS-STARTPTS"]


def test_sound_tracks_maps_video_and_selected_audio():
    op = sound_op.build({"mode": "tracks", "keep_index": 1}, _media(), None)
    assert op.output_args == ["-map", "0:v:0", "-map", "0:a:1"]


def test_sound_tracks_skips_video_map_when_no_video():
    op = sound_op.build({"mode": "tracks", "keep_index": 0}, _media(video=False), None)
    assert op.output_args == ["-map", "0:a:0"]


def test_sound_bitdepth_maps_to_pcm_codec():
    op = sound_op.build({"mode": "bitdepth", "depth": "24"}, _media(), None)
    assert op.non_video_output_args == ["-c:a", "pcm_s24le"]


def test_sound_compress_and_limit_filters():
    compress = sound_op.build({"mode": "volume", "method": "compress"}, _media(), None)
    assert "acompressor" in compress.audio_filter[0]
    limit = sound_op.build({"mode": "volume", "method": "limit"}, _media(), None)
    assert limit.audio_filter == ["alimiter=limit=-1dB"]


def test_crop_border_pads_symmetrically():
    op = crop_op.build({"mode": "border", "thickness": 15, "color": "white"}, _media(), None)
    assert op.video_filter == ["pad=iw+30:ih+30:15:15:color=white"]


def test_crop_detect_parses_last_cropdetect_line(monkeypatch):
    stderr = "crop=1920:800:0:140\ncrop=1920:800:0:140\ncrop=1920:816:0:132\n"
    monkeypatch.setattr(crop_op, "run_with_output", lambda *a, **k: stderr)
    assert crop_op._detect_crop(_media()) == (1920, 816, 0, 132)


def test_crop_detect_returns_none_when_no_matches(monkeypatch):
    monkeypatch.setattr(crop_op, "run_with_output", lambda *a, **k: "no crop lines here")
    assert crop_op._detect_crop(_media()) is None


def test_crop_detect_cancel_raises_plain_keyboard_interrupt(monkeypatch):
    # Ctrl+C should mean "bail out of the whole app" everywhere in ffx,
    # not a special-cased behavior just for this scan.
    from ffx.runner import FFmpegCancelled

    def raise_cancelled(*a, **k):
        raise FFmpegCancelled("cancelled by user")

    monkeypatch.setattr(crop_op, "run_with_output", raise_cancelled)
    try:
        crop_op._detect_crop(_media())
        assert False, "expected KeyboardInterrupt"
    except FFmpegCancelled:
        assert False, "FFmpegCancelled should not escape _detect_crop"
    except KeyboardInterrupt:
        pass


def test_crop_rect_prompt_bounds_against_the_effective_frame_not_the_source(monkeypatch):
    # Regression target: this exact sequence - scale to 1280 wide, then
    # a manual crop rectangle sized for the *original* 1920x1080 frame -
    # reached ffmpeg as a real, hard failure ("Failed to configure input
    # pad") before this fix, because crop.py's rect mode had no
    # dimension bounds at all, let alone ones aware of an earlier-queued
    # Scale. media here is what __main__.py actually passes: the
    # *effective* MediaInfo after Scale, not the raw probed one.
    source = _media()  # 1920x1080
    scale_params = {"mode": "width", "width": 1280, "algo": "lanczos"}
    effective = dimensions.effective_media(source, [(scale_op, scale_params)])
    assert (effective.primary_video.width, effective.primary_video.height) == (1280, 720)

    captured = {}

    def fake_ask_int(message, **kwargs):
        captured[message] = kwargs
        # Return whatever a real, correctly-bounded prompt would clamp
        # to - the max allowed, proving the bound itself is usable.
        return kwargs.get("max_allowed") or kwargs.get("default")

    monkeypatch.setattr(prompts, "choose_preset", lambda *a, **k: None)  # "Custom..."
    monkeypatch.setattr(prompts, "choose", lambda *a, **k: "rect")
    monkeypatch.setattr(prompts, "ask_int", fake_ask_int)

    params = crop_op.prompt(effective, None)

    assert captured["Crop width (px):"]["max_allowed"] == 1280
    assert captured["Crop height (px):"]["max_allowed"] == 720
    # width answer was 1280 (the max) -> x has zero room left.
    assert captured["Crop X offset (px from left, 0 = centered by ffmpeg):"]["max_allowed"] == 0
    assert params == {"mode": "rect", "width": 1280, "height": 720, "x": 0, "y": 0}


def test_crop_rect_prompt_has_no_bounds_without_a_video_stream(monkeypatch):
    # Graceful degradation, not a crash, when dimensions can't be
    # determined at all - falls back to today's unbounded behaviour.
    audio_only = MediaInfo(
        path=Path("in.mp3"), format_name="mp3", format_long_name="",
        duration=10.0, size=1000, bit_rate=1000,
        streams=[StreamInfo(index=0, codec_type="audio", codec_name="mp3")],
    )
    captured = {}

    def fake_ask_int(message, **kwargs):
        captured[message] = kwargs
        return kwargs.get("default")

    monkeypatch.setattr(prompts, "ask_int", fake_ask_int)
    params = crop_op._ask_rect(audio_only)

    assert captured["Crop width (px):"]["max_allowed"] is None
    assert params == {"mode": "rect", "width": 1280, "height": 720, "x": 0, "y": 0}
