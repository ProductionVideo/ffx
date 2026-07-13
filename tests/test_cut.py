from pathlib import Path

from ffx.models import MediaInfo, StreamInfo
from ffx.operations import cut as cut_op
from ffx.ui import prompts


def _media(*, video=True, frame_rate="30/1") -> MediaInfo:
    streams = []
    if video:
        streams.append(
            StreamInfo(index=0, codec_type="video", codec_name="h264", width=1920, height=1080, r_frame_rate=frame_rate)
        )
    return MediaInfo(
        path=Path("in.mp4"), format_name="mp4", format_long_name="MP4",
        duration=30.0, size=1000, bit_rate=1000, streams=streams,
    )


def test_frame_to_timestamp_matches_frame_over_fps():
    assert cut_op._frame_to_timestamp(150, 30.0) == "5.000000"
    assert cut_op._frame_to_timestamp(100, 24.0) == f"{100 / 24:.6f}"


def test_describe_reports_frames_when_specified_that_way():
    assert cut_op._describe("between", {"start_frame": 30, "end_frame": 90}) == "Cut from frame 30 to frame 90"
    assert (
        cut_op._describe("duration", {"start_frame": 0, "duration_frames": 60})
        == "Cut 60 frames starting at frame 0"
    )
    assert cut_op._describe("from_start", {"start_frame": 45}) == "Trim from frame 45 to the end"


def test_describe_falls_back_to_timestamps_when_not_frame_based():
    assert cut_op._describe("between", {"start": "1.0", "end": "5.0"}) == "Cut from 1.0 to 5.0"


def test_prompt_offers_frame_entry_and_converts_to_timestamp(monkeypatch):
    answers = iter([
        "between",   # choose: what kind of cut
        False,       # ask_confirm: Fast cut? -> No (frame-accurate)
        True,        # choose: Specify cut points by -> Frame number
        30,          # ask_int: Start frame
        150,         # ask_int: End frame
    ])
    monkeypatch.setattr(prompts, "choose", lambda *a, **k: next(answers))
    monkeypatch.setattr(prompts, "ask_confirm", lambda *a, **k: next(answers))
    monkeypatch.setattr(prompts, "ask_int", lambda *a, **k: next(answers))

    params = cut_op.prompt(_media(frame_rate="30/1"), None)

    assert params["start_frame"] == 30
    assert params["end_frame"] == 150
    assert params["start"] == "1.000000"
    assert params["end"] == "5.000000"


def test_prompt_skips_frame_entry_without_a_known_frame_rate(monkeypatch):
    # Audio-only media has no frame rate to convert against - the
    # "Specify cut points by" question must not even be asked.
    answers = iter([
        "from_start",  # choose: what kind of cut
        False,          # ask_confirm: Fast cut? -> No
    ])
    monkeypatch.setattr(prompts, "choose", lambda *a, **k: next(answers))
    monkeypatch.setattr(prompts, "ask_confirm", lambda *a, **k: next(answers))
    monkeypatch.setattr(prompts, "ask_timestamp", lambda *a, **k: "0")

    params = cut_op.prompt(_media(video=False), None)

    assert "start_frame" not in params
    assert params["start"] == "0"
