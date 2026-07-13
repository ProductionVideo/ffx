"""End-to-end smoke test: drives ffx.__main__.main() with every InquirerPy
prompt monkeypatched to a scripted answer, so the whole 5-step wiring runs
against a real ffmpeg/ffprobe without needing a TTY.
"""

import subprocess

import pytest

from ffx import __main__ as ffx_main
from ffx.models import OperationSettings
from ffx.ui import prompts


def _op(name, **kwargs):
    return OperationSettings(name=name, display_name=name.title(), description="", **kwargs)


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
