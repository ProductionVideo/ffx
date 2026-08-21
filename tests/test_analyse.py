from pathlib import Path

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
