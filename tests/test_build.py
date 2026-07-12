from pathlib import Path

from ffx.build import build_argv
from ffx.models import FFmpegJob, HardwareCapabilities, OperationSettings, OutputConfig

NO_HW = HardwareCapabilities(videotoolbox_available=False, hw_encoders=set(), hw_decoders=set())


def make_job(operations: list[OperationSettings], inputs=None) -> FFmpegJob:
    return FFmpegJob(
        inputs=inputs or [Path("in.mp4")],
        operations=operations,
        output=OutputConfig(path=Path("out.mp4")),
        hardware=NO_HW,
    )


def test_single_simple_op():
    op = OperationSettings(
        name="scale",
        display_name="Scale",
        description="",
        video_filter=["scale=1280:-2"],
        output_args=["-c:v", "libx264"],
    )
    argv = build_argv(make_job([op]))
    assert argv == [
        "ffmpeg",
        "-y",
        "-i",
        "in.mp4",
        "-vf",
        "scale=1280:-2",
        "-c:v",
        "libx264",
        "out.mp4",
    ]


def test_multiple_simple_ops_combine_into_one_vf_and_af():
    cut = OperationSettings(
        name="cut",
        display_name="Cut",
        description="",
        args_before_input=["-ss", "00:00:05"],
        output_args=["-t", "10"],
    )
    scale = OperationSettings(
        name="scale",
        display_name="Scale",
        description="",
        video_filter=["scale=1280:-2"],
    )
    crop = OperationSettings(
        name="crop",
        display_name="Crop",
        description="",
        video_filter=["crop=1280:720:0:0"],
    )
    volume = OperationSettings(
        name="volume",
        display_name="Volume",
        description="",
        audio_filter=["volume=1.5"],
    )
    argv = build_argv(make_job([cut, scale, crop, volume]))
    assert argv == [
        "ffmpeg",
        "-y",
        "-ss",
        "00:00:05",
        "-i",
        "in.mp4",
        "-vf",
        "scale=1280:-2,crop=1280:720:0:0",
        "-af",
        "volume=1.5",
        "-t",
        "10",
        "out.mp4",
    ]


def test_filter_complex_op_wins_over_simple_chains():
    scale = OperationSettings(
        name="scale",
        display_name="Scale",
        description="",
        video_filter=["scale=1280:-2"],
    )
    overlay = OperationSettings(
        name="composite",
        display_name="Composite",
        description="",
        filter_complex="[0:v][1:v]overlay=10:10[v]",
        output_args=["-map", "[v]"],
    )
    argv = build_argv(make_job([scale, overlay], inputs=[Path("in.mp4"), Path("logo.png")]))
    assert "-filter_complex" in argv
    assert argv[argv.index("-filter_complex") + 1] == "[0:v][1:v]overlay=10:10[v]"
    assert "-vf" not in argv
    assert "-map" in argv


def test_stream_copy_no_reencode_path():
    cut = OperationSettings(
        name="cut",
        display_name="Fast cut",
        description="",
        args_before_input=["-ss", "00:00:05"],
        output_args=["-t", "10", "-c", "copy"],
    )
    argv = build_argv(make_job([cut]))
    assert "-vf" not in argv
    assert "-af" not in argv
    assert argv[-5:] == ["-t", "10", "-c", "copy", "out.mp4"]
