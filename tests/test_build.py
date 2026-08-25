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
        # Audio was never touched - defaulted to a copy instead of
        # falling through to ffmpeg's own encoder for the container.
        "-c:a",
        "copy",
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


def test_untouched_video_and_audio_both_default_to_copy():
    # A pure metadata edit: touches neither track at all.
    metadata = OperationSettings(
        name="metadata", display_name="Metadata", description="",
        non_video_output_args=["-metadata", "title=x"],
    )
    argv = build_argv(make_job([metadata]))
    assert "-c:v" in argv and argv[argv.index("-c:v") + 1] == "copy"
    assert "-c:a" in argv and argv[argv.index("-c:a") + 1] == "copy"


def test_audio_only_op_defaults_video_to_copy():
    channels = OperationSettings(
        name="sound", display_name="Sound", description="",
        audio_filter=["pan=stereo|c0=c1|c1=c1"],
    )
    argv = build_argv(make_job([channels]))
    assert "-c:v" in argv and argv[argv.index("-c:v") + 1] == "copy"
    assert "-af" in argv  # audio was genuinely touched, no -c:a default added
    assert "-c:a" not in argv


def test_explicit_codec_choice_suppresses_the_default():
    convert = OperationSettings(
        name="convert", display_name="Convert", description="",
        output_args=["-c:v", "libx264"], non_video_output_args=["-c:a", "aac"],
    )
    argv = build_argv(make_job([convert]))
    assert argv.count("-c:v") == 1
    assert argv.count("-c:a") == 1


def test_forces_video_reencode_suppresses_the_video_default():
    # Regression target: a frame-rate change (Cut's accurate mode,
    # Repair's conform, Time's framerate op) needs a real re-encode
    # despite setting no video_filter - confirmed empirically that
    # ffmpeg silently ignores -r under -c:v copy rather than erroring,
    # so this must never coexist with the auto-copy default.
    framerate = OperationSettings(
        name="repair", display_name="Repair", description="",
        output_args=["-fps_mode", "cfr", "-r", "30"],
        forces_video_reencode=True,
    )
    argv = build_argv(make_job([framerate]))
    assert "-c:v" not in argv
    assert "-c:a" in argv and argv[argv.index("-c:a") + 1] == "copy"


def test_forces_audio_reencode_suppresses_the_audio_default():
    resample = OperationSettings(
        name="sound", display_name="Sound", description="",
        non_video_output_args=["-ar", "48000"],
        forces_audio_reencode=True,
    )
    argv = build_argv(make_job([resample]))
    assert "-c:a" not in argv
    assert "-c:v" in argv and argv[argv.index("-c:v") + 1] == "copy"


def test_no_default_copy_when_output_extension_changes():
    # Convert (or Thumbnail/Sound's audio extract) already picks its own
    # codecs on purpose - the source's own codec isn't even guaranteed
    # to be valid in a different container.
    extract = OperationSettings(
        name="sound", display_name="Sound", description="",
        non_video_output_args=["-vn", "-c:a", "libmp3lame"],
    )
    job = FFmpegJob(
        inputs=[Path("in.mp4")], operations=[extract],
        output=OutputConfig(path=Path("out.mp3")), hardware=NO_HW,
    )
    argv = build_argv(job)
    assert "-c:v" not in argv


def test_no_default_copy_when_filter_complex_present():
    # Composite/Sequence's filter_complex sometimes passes a stream
    # through untouched (Composite's audio via a plain "-map 0:a?") in
    # ways this can't safely distinguish from one it doesn't reference -
    # left exactly as before rather than risk misreading the graph.
    composite = OperationSettings(
        name="composite", display_name="Composite", description="",
        filter_complex="[0:v][1:v]overlay[outv]",
        output_args=["-map", "[outv]", "-map", "0:a?"],
    )
    argv = build_argv(make_job([composite]))
    assert "-c:v" not in argv
    assert "-c:a" not in argv
