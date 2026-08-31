"""End-to-end smoke test: drives ffx.__main__.main() with every InquirerPy
prompt monkeypatched to a scripted answer, so the whole 5-step wiring runs
against a real ffmpeg/ffprobe without needing a TTY.
"""

import subprocess
from pathlib import Path

import pytest

from ffx import __main__ as ffx_main
from ffx.models import MediaInfo, OperationSettings, StreamInfo
from ffx.ui import prompts


def _op(name, **kwargs):
    return OperationSettings(name=name, display_name=name.title(), description="", **kwargs)


def _media() -> MediaInfo:
    video = StreamInfo(index=0, codec_type="video", codec_name="h264", width=1920, height=1080)
    return MediaInfo(
        path=Path("in.mp4"), format_name="mp4", format_long_name="",
        duration=10.0, size=1000, bit_rate=5000, streams=[video],
    )


def test_run_analyse_declining_back_to_pipeline_signals_restart(monkeypatch):
    # Regression: "Back to the pipeline?" used to discard its answer
    # entirely - "y" and "n" were indistinguishable, both just fell
    # through to the same "continue as normal" behaviour. "n" must now
    # actually mean something different: restart with a new file.
    monkeypatch.setattr(prompts, "run_wizard", lambda fn, *a, **k: {"checks": ["streams"]})
    monkeypatch.setattr(prompts, "ask_confirm", lambda *a, **k: False)  # "n"

    assert ffx_main._run_analyse(_media()) is True


def test_run_analyse_accepting_back_to_pipeline_continues_normally(monkeypatch):
    monkeypatch.setattr(prompts, "run_wizard", lambda fn, *a, **k: {"checks": ["streams"]})
    monkeypatch.setattr(prompts, "ask_confirm", lambda *a, **k: True)  # "y" / Enter

    assert ffx_main._run_analyse(_media()) is False


def test_run_analyse_cancelling_the_checks_question_does_not_restart(monkeypatch):
    # Backing out of "which checks?" (Esc/Ctrl+Z) is "nevermind", not
    # "restart everything" - the trailing gate is never even reached.
    def fail_if_asked(*a, **k):
        raise AssertionError("the trailing confirm should not be reached")

    monkeypatch.setattr(prompts, "run_wizard", lambda fn, *a, **k: None)
    monkeypatch.setattr(prompts, "ask_confirm", fail_if_asked)

    assert ffx_main._run_analyse(_media()) is False


def test_filter_drop_conflict_flags_vf_alongside_filter_complex():
    ops = [
        _op("composite", filter_complex="[0:v]overlay[out]"),
        _op("scale", video_filter=["scale=160:-2"]),
    ]
    assert ffx_main._filter_drop_conflict(ops) == ("Composite", ["Scale"])


def test_filter_drop_conflict_quiet_without_filter_complex():
    ops = [_op("scale", video_filter=["scale=160:-2"]), _op("convert", output_args=["-c:v", "libx264"])]
    assert ffx_main._filter_drop_conflict(ops) is None


def test_filter_drop_conflict_quiet_when_others_have_no_filters():
    ops = [
        _op("composite", filter_complex="[0:v]overlay[out]"),
        _op("convert", output_args=["-c:v", "libx264"]),
    ]
    assert ffx_main._filter_drop_conflict(ops) is None


def test_audio_copy_filter_conflict_flags_channels_alongside_copy_audio():
    # The exact combination ffmpeg hard-errors on: "Filtering and
    # streamcopy cannot be used together" - Convert's "Copy (no
    # re-encode)" audio option puts "-c:a copy" in non_video_output_args,
    # any op with an audio_filter (channels/volume/fade/...) conflicts.
    ops = [
        _op("convert", non_video_output_args=["-c:v", "copy", "-c:a", "copy"]),
        _op("sound", audio_filter=["pan=stereo|c0=c1|c1=c1"]),
    ]
    assert ffx_main._has_audio_copy_filter_conflict(ops) is True


def test_audio_copy_filter_conflict_quiet_with_a_real_audio_codec():
    ops = [
        _op("convert", non_video_output_args=["-c:v", "copy", "-c:a", "aac"]),
        _op("sound", audio_filter=["pan=stereo|c0=c1|c1=c1"]),
    ]
    assert ffx_main._has_audio_copy_filter_conflict(ops) is False


def test_audio_copy_filter_conflict_quiet_without_any_audio_filter():
    ops = [
        _op("convert", non_video_output_args=["-c:v", "copy", "-c:a", "copy"]),
        _op("scale", video_filter=["scale=160:-2"]),
    ]
    assert ffx_main._has_audio_copy_filter_conflict(ops) is False


def _media_with_audio(codec_name: str) -> MediaInfo:
    video = StreamInfo(index=0, codec_type="video", codec_name="h264", width=1920, height=1080)
    audio = StreamInfo(index=1, codec_type="audio", codec_name=codec_name)
    return MediaInfo(
        path=Path("in.mp4"), format_name="mp4", format_long_name="",
        duration=10.0, size=1000, bit_rate=5000, streams=[video, audio],
    )


def test_default_audio_codec_matches_pcm_source_exactly():
    # Regression: a PCM source run through any audio filter (nothing
    # touched video, no Convert step) used to silently come out as AAC -
    # ffmpeg's own container default, not a stream copy (impossible once
    # a filter's applied) and not the source's own format either.
    ops = [_op("sound", audio_filter=["pan=stereo|c0=c1|c1=c1"])]
    default_op = ffx_main._default_audio_codec_op(ops, _media_with_audio("pcm_s24le"))
    assert default_op.non_video_output_args == ["-c:a", "pcm_s24le"]


def test_default_audio_codec_maps_decoder_name_to_encoder_name():
    # mp3 decodes as "mp3" but ffmpeg can only *encode* mp3 via
    # "libmp3lame" - reusing the probed codec_name verbatim would fail.
    ops = [_op("sound", audio_filter=["pan=stereo|c0=c1|c1=c1"])]
    default_op = ffx_main._default_audio_codec_op(ops, _media_with_audio("mp3"))
    assert default_op.non_video_output_args == ["-c:a", "libmp3lame"]


def test_default_audio_codec_none_when_audio_untouched():
    # build_argv's own copy-default already covers this case - adding a
    # synthetic -c:a here too would be redundant, not wrong, but this
    # confirms the two mechanisms don't double up.
    ops = [_op("scale", video_filter=["scale=160:-2"])]
    assert ffx_main._default_audio_codec_op(ops, _media_with_audio("pcm_s24le")) is None


def test_default_audio_codec_none_when_a_codec_was_already_chosen():
    ops = [
        _op("convert", non_video_output_args=["-c:a", "mp3"]),
        _op("sound", audio_filter=["pan=stereo|c0=c1|c1=c1"]),
    ]
    assert ffx_main._default_audio_codec_op(ops, _media_with_audio("pcm_s24le")) is None


def test_default_audio_codec_none_for_an_unmapped_source_codec():
    # A wrong guess here is a silent, unrequested format change - safer
    # to fall through to ffmpeg's own default (today's behaviour) than
    # risk mismatching an exotic/unrecognized source codec.
    ops = [_op("sound", audio_filter=["pan=stereo|c0=c1|c1=c1"])]
    assert ffx_main._default_audio_codec_op(ops, _media_with_audio("wmav2")) is None


def test_default_audio_codec_none_when_forces_audio_reencode_without_filter():
    # Sound's resample mode: needs a real re-encode (forces_audio_reencode)
    # but sets no audio_filter - must still be recognized as "audio is
    # being touched" so the source format is preserved here too.
    ops = [_op("sound", non_video_output_args=["-ar", "48000"], forces_audio_reencode=True)]
    default_op = ffx_main._default_audio_codec_op(ops, _media_with_audio("aac"))
    assert default_op.non_video_output_args == ["-c:a", "aac"]


def test_select_operations_gives_crop_the_effective_frame_not_the_source(monkeypatch):
    # Integration test for the actual reported bug: drives
    # _select_operations itself (not crop.prompt() in isolation) with
    # Scale already queued ahead of it, confirming the wiring in
    # __main__.py - not just crop.py's own logic - correctly narrows
    # Crop's bounds to the post-scale frame.
    from ffx.models import HardwareCapabilities
    from ffx.operations import scale as scale_op

    caps = HardwareCapabilities(videotoolbox_available=False, hw_encoders=set(), hw_decoders=set())
    scale_params = {"mode": "width", "width": 1280, "algo": "lanczos"}
    ordered_ops = [(scale_op, scale_params)]

    captured = {}

    def fake_ask_int(message, **kwargs):
        captured[message] = kwargs
        return kwargs.get("max_allowed") or kwargs.get("default")

    choose_answers = iter(["crop", "rect", "done"])
    monkeypatch.setattr(prompts, "run_wizard", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(prompts, "choose_preset", lambda *a, **k: None)
    monkeypatch.setattr(prompts, "choose", lambda *a, **k: next(choose_answers))
    monkeypatch.setattr(prompts, "ask_int", fake_ask_int)

    result = ffx_main._select_operations(_media(), caps, ordered_ops)

    assert captured["Crop width (px):"]["max_allowed"] == 1280
    assert captured["Crop height (px):"]["max_allowed"] == 720
    crop_params = result[-1][1]
    assert (crop_params["width"], crop_params["height"]) == (1280, 720)


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


def test_convert_then_scale_end_to_end(monkeypatch, tmp_path, sample_clip):
    answers = iter(
        [
            sample_clip,  # ask_existing_path: input file
            "convert",  # choose: category
            "h264",  # choose: video codec
            "mp4",  # choose: container
            "aac",  # choose: audio codec
            "software",  # choose: encoder (engine)
            "manual",  # choose: Quality menu -> Manual
            "23",  # ask_text: manual CRF
            "scale",  # choose: category (pipeline menu loops back automatically)
            None,  # choose_preset: Custom...
            "width",  # choose: scale mode
            "160",  # ask_text: target width
            "bilinear",  # choose: algorithm
            "done",  # choose: category menu -> Done
            tmp_path,  # ask_output_path: output directory
            True,  # ask_confirm: run the command?
            False,  # ask_confirm: save as recipe?
        ]
    )

    monkeypatch.setattr(prompts, "ask_existing_path", lambda *a, **k: next(answers))
    monkeypatch.setattr(prompts, "choose", lambda *a, **k: next(answers))
    monkeypatch.setattr(prompts, "choose_preset", lambda *a, **k: next(answers))
    monkeypatch.setattr(prompts, "ask_confirm", lambda *a, **k: next(answers))
    monkeypatch.setattr(prompts, "ask_text", lambda *a, **k: next(answers))
    monkeypatch.setattr(prompts, "ask_output_path", lambda *a, **k: next(answers))

    ffx_main.main()

    outputs = list(tmp_path.glob("sample.*"))
    produced = [p for p in outputs if p != sample_clip]
    assert len(produced) == 1
    out_path = produced[0]
    assert out_path.suffix == ".mp4"

    probe_out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert probe_out == "160,120"
