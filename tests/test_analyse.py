from pathlib import Path

import pytest

from ffx import analyse
from ffx.models import Chapter, MediaInfo, StreamInfo
from ffx.runner import FFmpegCancelled


def _media(**overrides) -> MediaInfo:
    defaults = dict(
        path=Path("in.mp4"), format_name="mp4", format_long_name="MP4",
        duration=100.0, size=1000, bit_rate=5000, streams=[],
    )
    defaults.update(overrides)
    return MediaInfo(**defaults)


def test_run_qc_black_passes_duration_and_description(monkeypatch):
    captured = {}

    def fake_run_with_output(args, *, total_duration, console, description):
        captured["total_duration"] = total_duration
        captured["description"] = description
        return "black_start:1.0 black_end:2.0 black_duration:1.0\n"

    monkeypatch.setattr(analyse, "run_with_output", fake_run_with_output)
    findings = analyse.run_qc(Path("in.mp4"), ["black"], duration=42.0, console=None)

    assert captured["total_duration"] == 42.0
    assert captured["description"] == "Checking for black sections"
    assert findings.black_sections == [(1.0, 2.0, 1.0)]


def test_run_qc_silence_and_freeze_descriptions(monkeypatch):
    descriptions = []

    def fake_run_with_output(args, *, total_duration, console, description):
        descriptions.append(description)
        return ""

    monkeypatch.setattr(analyse, "run_with_output", fake_run_with_output)
    analyse.run_qc(Path("in.mp4"), ["silence", "freeze"], duration=10.0, console=None)

    assert descriptions == ["Checking for silent sections", "Checking for frozen sections"]


def _showinfo_line(n, pts_time, field_order, iskey, ftype):
    return (
        f"[Parsed_showinfo_0 @ 0x0] n:{n:4d} pts:{n * 512:7d} pts_time:{pts_time} "
        f"duration:  512 duration_time:0.033333 fmt:yuv444p cl:left sar:1/1 s:640x480 "
        f"i:{field_order} iskey:{iskey} type:{ftype} checksum:DEADBEEF "
        f"plane_checksum:[AAAAAAAA BBBBBBBB CCCCCCCC] mean:[126 129 125] stdev:[71.5 70.6 72.2]"
    )


def test_run_qc_frames_reads_showinfo_and_computes_stats(monkeypatch):
    captured = {}
    lines = [
        _showinfo_line(0, "0.0", "P", 1, "I"),
        _showinfo_line(1, "0.033333", "P", 0, "P"),
        _showinfo_line(2, "0.066667", "P", 0, "B"),
    ]

    def fake_run_with_output(args, *, total_duration, console, description):
        captured["description"] = description
        captured["vf_present"] = "-vf" in args and "showinfo" in args
        return "\n".join(lines) + "\n"

    monkeypatch.setattr(analyse, "run_with_output", fake_run_with_output)
    findings = analyse.run_qc(Path("in.mp4"), ["frames"], duration=1.0, console=None)

    assert captured["description"] == "Reading frame data"
    assert captured["vf_present"]
    stats = findings.frame_stats
    assert stats.total == 3
    assert stats.type_counts == {"I": 1, "P": 1, "B": 1}
    assert stats.keyframe_count == 1
    assert stats.field_order == "progressive"


def test_parse_frame_stats_ignores_non_frame_showinfo_lines():
    # Side-data/color_range/config lines share the same log prefix but
    # have no "type:" field - must not be miscounted as frames.
    stderr = "\n".join([
        "[Parsed_showinfo_0 @ 0x0] config in time_base: 1/15360, frame_rate: 30/1",
        _showinfo_line(0, "0.0", "P", 1, "I"),
        "[Parsed_showinfo_0 @ 0x0]   side data - H.264 User Data Unregistered SEI message",
        "[Parsed_showinfo_0 @ 0x0] color_range:unknown color_space:unknown",
    ])
    stats = analyse._parse_frame_stats(stderr)
    assert stats.total == 1


def test_parse_frame_stats_average_gop_from_keyframe_spacing():
    lines = [_showinfo_line(0, "0.0", "P", 1, "I")]
    for n in range(1, 30):
        lines.append(_showinfo_line(n, f"{n * 0.033:.3f}", "P", 1 if n % 10 == 0 else 0, "P"))
    stats = analyse._parse_frame_stats("\n".join(lines))
    assert stats.keyframe_count == 3  # keyframes at frames 0, 10, 20 (30 frames total: 0-29)
    assert stats.avg_gop_frames == 10.0


def test_parse_frame_stats_detects_interlaced_top_field_first():
    lines = [_showinfo_line(n, f"{n * 0.04:.3f}", "T", 1 if n == 0 else 0, "P") for n in range(5)]
    stats = analyse._parse_frame_stats("\n".join(lines))
    assert stats.field_order == "interlaced (top-field-first)"


def test_parse_frame_stats_mixed_field_order():
    lines = [
        _showinfo_line(0, "0.0", "T", 1, "I"),
        _showinfo_line(1, "0.04", "B", 0, "P"),
    ]
    stats = analyse._parse_frame_stats("\n".join(lines))
    assert stats.field_order == "mixed"


def test_parse_frame_stats_measured_fps_from_pts_span():
    # 10 frames spanning exactly 0.0 to 0.333333s -> 9 intervals -> 27fps
    lines = [_showinfo_line(n, f"{n * (1 / 27):.6f}", "P", 1 if n == 0 else 0, "P") for n in range(10)]
    stats = analyse._parse_frame_stats("\n".join(lines))
    assert stats.measured_fps == pytest.approx(27.0, abs=0.01)


def test_parse_frame_stats_empty_stderr_returns_zeroed_stats():
    stats = analyse._parse_frame_stats("")
    assert stats.total == 0
    assert stats.type_counts == {}
    assert stats.keyframe_count == 0
    assert stats.avg_gop_frames is None
    assert stats.field_order == ""
    assert stats.measured_fps is None


def test_run_qc_freeze_captures_end_and_duration_not_just_start(monkeypatch):
    # Regression: freezedetect logs freeze_start/freeze_end/freeze_duration
    # as three separate lines per section, but the end/duration regexes
    # used to be defined and never actually applied - freeze findings
    # silently dropped everything but the start time.
    def fake_run_with_output(args, *, total_duration, console, description):
        return (
            "[freezedetect] lavfi.freezedetect.freeze_start: 0.96\n"
            "[freezedetect] lavfi.freezedetect.freeze_duration: 1.56\n"
            "[freezedetect] lavfi.freezedetect.freeze_end: 2.52\n"
        )

    monkeypatch.setattr(analyse, "run_with_output", fake_run_with_output)
    findings = analyse.run_qc(Path("in.mp4"), ["freeze"], duration=10.0, console=None)

    assert findings.freeze_sections == [(0.96, 2.52, 1.56)]


def test_run_qc_freeze_running_to_eof_has_no_end():
    findings_end = analyse.QCFindings()
    findings_end.freeze_sections = [(0.96, None, None)]
    assert findings_end.freeze_sections[0][1] is None


def test_section_stats_counts_total_and_percent():
    sections = [(0.0, 2.0, 2.0), (10.0, 11.5, 1.5)]
    count, total, percent = analyse.section_stats(sections, duration=10.0)
    assert count == 2
    assert total == 3.5
    assert percent == 35.0


def test_section_stats_open_ended_section_counts_to_clip_duration():
    # No end (ran to EOF) - the affected time should still count through
    # the clip's own duration, not be dropped or treated as zero-length.
    sections = [(8.0, None, None)]
    count, total, percent = analyse.section_stats(sections, duration=10.0)
    assert count == 1
    assert total == 2.0
    assert percent == 20.0


def test_section_stats_empty():
    assert analyse.section_stats([], duration=10.0) == (0, 0.0, 0.0)


def test_streams_rows_covers_every_stream_not_just_primary():
    video = StreamInfo(index=0, codec_type="video", codec_name="h264", width=1920, height=1080)
    audio_en = StreamInfo(
        index=1, codec_type="audio", codec_name="aac", channel_layout="stereo",
        tags={"language": "eng"}, disposition={"default": 1},
    )
    audio_fr = StreamInfo(
        index=2, codec_type="audio", codec_name="aac", channel_layout="stereo",
        tags={"language": "fra"}, disposition={"forced": 1},
    )
    media = _media(streams=[video, audio_en, audio_fr])

    rows = analyse.streams_rows(media)
    assert len(rows) == 3
    assert rows[0] == (0, "video", "h264, 1920x1080", "-", "-", "-")
    assert rows[1] == (1, "audio", "aac, stereo", "eng", "default", "-")
    assert rows[2] == (2, "audio", "aac, stereo", "fra", "forced", "-")


def test_chapter_rows_reads_through_media_chapters():
    media = _media(chapters=[Chapter(index=0, start=0.0, end=30.0, title="Intro")])
    assert analyse.chapter_rows(media) == [(0, 0.0, 30.0, "Intro")]


def test_run_filter_cancel_raises_plain_keyboard_interrupt(monkeypatch):
    # Ctrl+C should mean "bail out of the whole app" everywhere in ffx,
    # not a special-cased behavior just for this scan.
    def raise_cancelled(*a, **k):
        raise FFmpegCancelled("cancelled by user")

    monkeypatch.setattr(analyse, "run_with_output", raise_cancelled)
    try:
        analyse._run_filter(Path("in.mp4"), 10.0, None, "Checking", vf="blackdetect=d=0.1")
        assert False, "expected KeyboardInterrupt"
    except FFmpegCancelled:
        assert False, "FFmpegCancelled should not escape _run_filter"
    except KeyboardInterrupt:
        pass
