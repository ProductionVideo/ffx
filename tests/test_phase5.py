"""Thumbnail, Caption, and Timecode - argv construction."""
from pathlib import Path

from ffx.build import build_argv
from ffx.models import FFmpegJob, HardwareCapabilities, MediaInfo, OutputConfig, StreamInfo
from ffx.operations import caption, thumbnail, timecode

CAPS = HardwareCapabilities(videotoolbox_available=False, hw_encoders=set(), hw_decoders=set())


def _media(duration=60.0) -> MediaInfo:
    video = StreamInfo(index=0, codec_type="video", codec_name="h264", width=1920, height=1080,
                       avg_frame_rate="30000/1001")
    return MediaInfo(
        path=Path("in.mp4"), format_name="mp4", format_long_name="",
        duration=duration, size=1000, bit_rate=5_000_000, streams=[video],
    )


def _argv_for(op) -> list[str]:
    job = FFmpegJob(inputs=[Path("in.mp4")], operations=[op],
                    output=OutputConfig(path=Path("out.png")), hardware=CAPS)
    return build_argv(job)


def test_thumbnail_frame_fast_seeks_and_takes_one_frame():
    op = thumbnail.build({"mode": "frame", "timestamp": "12.5", "format": "png"}, _media(), CAPS)
    argv = _argv_for(op)
    assert argv.index("-ss") < argv.index("-i")
    assert " ".join(argv).count("-frames:v 1") == 1
    assert thumbnail.output_extension({"format": "jpg"}) == "jpg"


def test_thumbnail_sheet_samples_evenly():
    op = thumbnail.build(
        {"mode": "sheet", "columns": 4, "rows": 3, "tile_width": 320, "format": "png"}, _media(60.0), CAPS
    )
    vf = " ".join(op.video_filter)
    # 12 tiles over 60s -> one frame every 5s
    assert "fps=0.200000" in vf
    assert "tile=4x3" in vf
    assert "scale=320:-1" in vf
    assert op.output_args == ["-frames:v", "1"]


def test_caption_burn_quotes_the_path():
    op = caption.build({"mode": "burn", "path": "/tmp/My Subs.srt"}, _media(), CAPS)
    assert op.video_filter == ["subtitles='/tmp/My Subs.srt'"]


def test_caption_soft_maps_subtitle_input():
    op = caption.build({"mode": "soft", "path": "subs.srt", "codec": "mov_text"}, _media(), CAPS)
    argv = _argv_for(op)
    joined = " ".join(argv)
    assert "-map 0 -map 1:0" in joined
    assert "-c:s mov_text" in joined
    assert str(Path("subs.srt")) in argv


def test_timecode_set_is_metadata_only():
    op = timecode.build({"mode": "set", "timecode": "01:00:00:00"}, _media(), CAPS)
    assert op.non_video_output_args == ["-timecode", "01:00:00:00"]
    assert op.video_filter == []


def test_timecode_burn_escapes_colons_and_uses_source_rate():
    op = timecode.build({"mode": "burn", "timecode": "01:00:00:00"}, _media(), CAPS)
    vf = op.video_filter[0]
    assert r"timecode='01\:00\:00\:00'" in vf
    assert "rate=30000/1001" in vf
