from pathlib import Path

from ffx.build import build_argv, build_two_pass_argvs, needs_two_pass
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


def test_normal_build_includes_both_output_arg_lists():
    convert = OperationSettings(
        name="convert",
        display_name="Convert",
        description="",
        output_args=["-c:v", "libx264", "-b:v", "2000k"],
        non_video_output_args=["-c:a", "aac", "-b:a", "192k"],
    )
    argv = build_argv(make_job([convert]))
    assert argv[-9:] == ["-c:v", "libx264", "-b:v", "2000k", "-c:a", "aac", "-b:a", "192k", "out.mp4"]


def test_needs_two_pass_false_without_any_op_requesting_it():
    op = OperationSettings(name="scale", display_name="Scale", description="", video_filter=["scale=1280:-2"])
    assert needs_two_pass(make_job([op])) is False


def test_needs_two_pass_false_when_filter_complex_present_even_if_requested():
    # The pass-1 builder only reasons about the simple video_filter chain,
    # so a filter_complex job must fall back to single-pass rather than
    # risk an incorrect analysis pass.
    convert = OperationSettings(
        name="convert", display_name="Convert", description="", output_args=["-c:v", "libx264"], two_pass=True,
    )
    overlay = OperationSettings(
        name="composite", display_name="Composite", description="", filter_complex="[0:v][1:v]overlay[v]",
    )
    assert needs_two_pass(make_job([convert, overlay])) is False


def test_extra_inputs_get_appended_after_main_input_with_their_args():
    watermark = OperationSettings(
        name="composite",
        display_name="Composite",
        description="",
        extra_inputs=[Path("logo.png")],
        extra_input_args=[["-loop", "1"]],
        filter_complex="[{in0}]format=rgba[wm];[0:v][wm]overlay=10:10[outv]",
        output_args=["-map", "[outv]"],
    )
    argv = build_argv(make_job([watermark]))
    assert argv[:8] == ["ffmpeg", "-y", "-i", "in.mp4", "-loop", "1", "-i", "logo.png"]
    fc = argv[argv.index("-filter_complex") + 1]
    assert fc == "[1]format=rgba[wm];[0:v][wm]overlay=10:10[outv]"


def test_extra_input_placeholder_resolves_after_multiple_job_inputs():
    # job.inputs already has 2 entries (a batch/multi-input job), so the
    # op's own extra input must land at index 2, not 1.
    overlay = OperationSettings(
        name="composite",
        display_name="Composite",
        description="",
        extra_inputs=[Path("bg.png")],
        extra_input_args=[[]],
        filter_complex="[0:v][{in0}]overlay[outv]",
        output_args=["-map", "[outv]"],
    )
    argv = build_argv(make_job([overlay], inputs=[Path("a.mp4"), Path("b.mp4")]))
    assert argv[:6] == ["ffmpeg", "-y", "-i", "a.mp4", "-i", "b.mp4"]
    assert argv[6:8] == ["-i", "bg.png"]
    fc = argv[argv.index("-filter_complex") + 1]
    assert fc == "[0:v][2]overlay[outv]"


def test_build_two_pass_argvs():
    cut = OperationSettings(
        name="cut",
        display_name="Cut",
        description="",
        args_before_input=["-ss", "5"],
        output_args=["-t", "10"],
    )
    convert = OperationSettings(
        name="convert",
        display_name="Convert",
        description="",
        video_filter=["scale=1280:-2"],
        output_args=["-c:v", "libx264", "-b:v", "2000k"],
        non_video_output_args=["-c:a", "aac", "-b:a", "192k"],
        two_pass=True,
    )
    job = make_job([cut, convert])
    assert needs_two_pass(job) is True

    pass1, pass2 = build_two_pass_argvs(job, "/tmp/ffx-pass")

    # Pass 1: same trim/filters as the real encode, video codec settings
    # only, no audio, discarded to null.
    assert pass1[:6] == ["ffmpeg", "-y", "-ss", "5", "-i", "in.mp4"]
    assert "-vf" in pass1 and pass1[pass1.index("-vf") + 1] == "scale=1280:-2"
    assert "-t" in pass1 and "10" in pass1
    assert "-c:v" in pass1 and "libx264" in pass1
    assert "-b:v" in pass1 and "2000k" in pass1
    assert "-c:a" not in pass1
    assert "-b:a" not in pass1
    assert pass1[-8:] == ["-an", "-pass", "1", "-passlogfile", "/tmp/ffx-pass", "-f", "null", "/dev/null"]

    # Pass 2: identical to a normal single-pass build, plus -pass 2.
    normal = build_argv(job)
    assert pass2[:-1] == normal[:-1] + ["-pass", "2", "-passlogfile", "/tmp/ffx-pass"]
    assert pass2[-1] == "out.mp4"
