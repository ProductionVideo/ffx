from pathlib import Path

from ffx.models import MediaInfo, StreamInfo
from ffx.operations import metadata as metadata_op
from ffx.operations import repair as repair_op


def _media(*, video=True, audio=True, frame_rate="30/1", duration=10.0) -> MediaInfo:
    streams = []
    if video:
        streams.append(
            StreamInfo(index=0, codec_type="video", codec_name="h264", width=1920, height=1080, r_frame_rate=frame_rate)
        )
    if audio:
        streams.append(StreamInfo(index=len(streams), codec_type="audio", codec_name="aac", channels=2))
    return MediaInfo(
        path=Path("in.mp4"), format_name="mp4", format_long_name="MP4",
        duration=duration, size=1000, bit_rate=1000, streams=streams,
    )


def test_metadata_edit_sets_format_and_stream_tags():
    params = {"mode": "edit", "values": {"title": "My Title", "language": "eng"}}
    op = metadata_op.build(params, _media(), None)
    assert "-metadata" in op.non_video_output_args
    assert "title=My Title" in op.non_video_output_args
    assert "-metadata:s:v:0" in op.non_video_output_args
    assert "-metadata:s:a:0" in op.non_video_output_args
    assert op.non_video_output_args.count("language=eng") == 2


def test_metadata_edit_is_pure_and_can_build_twice():
    # build() is called once for the pipeline preview panel and again for
    # the real job - it must not mutate params in a way that breaks the
    # second call.
    params = {"mode": "edit", "values": {"title": "T", "language": "eng"}}
    first = metadata_op.build(params, _media(), None)
    second = metadata_op.build(params, _media(), None)
    assert first.non_video_output_args == second.non_video_output_args


def test_metadata_strip_uses_map_metadata():
    op = metadata_op.build({"mode": "strip"}, _media(), None)
    assert op.non_video_output_args == ["-map_metadata", "-1"]


def test_repair_faststart():
    op = repair_op.build({"mode": "faststart"}, _media(), None)
    assert op.non_video_output_args == ["-movflags", "+faststart"]


def test_repair_genpts_is_input_side():
    op = repair_op.build({"mode": "genpts"}, _media(), None)
    assert op.args_before_input == ["-fflags", "+genpts"]
    assert op.output_args == []


def test_repair_vfr_to_cfr_uses_explicit_fps():
    op = repair_op.build({"mode": "vfr_to_cfr", "fps": "24"}, _media(), None)
    assert op.output_args == ["-fps_mode", "cfr", "-r", "24"]


def test_repair_vfr_to_cfr_falls_back_to_source_frame_rate():
    op = repair_op.build({"mode": "vfr_to_cfr", "fps": None}, _media(frame_rate="25/1"), None)
    assert op.output_args == ["-fps_mode", "cfr", "-r", "25.0"]


def test_repair_remux_uses_stream_copy():
    op = repair_op.build({"mode": "remux"}, _media(), None)
    assert op.output_args == ["-c", "copy"]
    assert "ignore_err" in op.args_before_input
