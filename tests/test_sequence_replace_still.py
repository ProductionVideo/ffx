"""Sequence (concat), Sound replace/mix, and Time's still-image mode -
argv construction plus the {inN} placeholder resolution they rely on."""
from pathlib import Path

from ffx.build import build_argv
from ffx.models import FFmpegJob, HardwareCapabilities, MediaInfo, OutputConfig, StreamInfo
from ffx.operations import sequence, sound, time as time_op

CAPS = HardwareCapabilities(videotoolbox_available=False, hw_encoders=set(), hw_decoders=set())


def _media(*, audio=True, width=1920, height=1080, format_name="mov,mp4,m4a,3gp,3g2,mj2") -> MediaInfo:
    streams = [
        StreamInfo(index=0, codec_type="video", codec_name="h264", width=width, height=height,
                   avg_frame_rate="30/1"),
    ]
    if audio:
        streams.append(StreamInfo(index=1, codec_type="audio", codec_name="aac"))
    return MediaInfo(
        path=Path("in.mp4"), format_name=format_name, format_long_name="",
        duration=10.0, size=1000, bit_rate=5_000_000, streams=streams,
    )


def _argv_for(op, media):
    job = FFmpegJob(inputs=[media.path], operations=[op],
                    output=OutputConfig(path=Path("out.mp4")), hardware=CAPS)
    return build_argv(job)


# --- Sequence ---------------------------------------------------------------

def test_sequence_concat_two_clips_with_audio():
    op = sequence.build({"paths": ["b.mp4", "c.mp4"], "audio": True}, _media(), CAPS)
    argv = _argv_for(op, _media())
    fc = argv[argv.index("-filter_complex") + 1]
    # Extra inputs land at ffmpeg indices 1 and 2; every chain is conformed
    # to the main clip's canvas and the streams interleave v/a for concat.
    assert "[1:v]scale=1920:1080" in fc
    assert "[2:v]scale=1920:1080" in fc
    assert "concat=n=3:v=1:a=1[outv][outa]" in fc
    assert "[1:a]" in fc and "[2:a]" in fc
    assert argv[argv.index("-i") :].count("-i") == 3
    assert "-map" in argv and "[outv]" in argv and "[outa]" in argv


def test_sequence_silent_when_audio_false():
    op = sequence.build({"paths": ["b.mp4"], "audio": False}, _media(audio=False), CAPS)
    argv = _argv_for(op, _media(audio=False))
    fc = argv[argv.index("-filter_complex") + 1]
    assert "concat=n=2:v=1:a=0[outv]" in fc
    assert "[outa]" not in fc
    assert "[outa]" not in argv


# --- Sound replace / mix ----------------------------------------------------

def test_replace_audio_maps_extra_input():
    op = sound.build({"mode": "replace", "path": "music.wav", "codec": "aac"}, _media(), CAPS)
    argv = _argv_for(op, _media())
    joined = " ".join(argv)
    # The {in0} placeholder resolves to the real input index (1) even
    # though this op has no filter_complex.
    assert "-map 0:v? -map 1:a" in joined
    assert "-shortest" in joined
    assert "-c:a aac" in joined
    assert str(Path("music.wav")) in argv


def test_replace_audio_copy_codec():
    op = sound.build({"mode": "replace", "path": "music.wav", "codec": "copy"}, _media(), CAPS)
    assert "-c:a copy" in " ".join(_argv_for(op, _media()))


def test_mix_audio_uses_amix_at_level():
    op = sound.build({"mode": "mix", "path": "bed.mp3", "level": 0.25}, _media(), CAPS)
    argv = _argv_for(op, _media())
    fc = argv[argv.index("-filter_complex") + 1]
    assert "[1:a]volume=0.25[mixin]" in fc
    assert "amix=inputs=2:duration=first" in fc
    assert "-map 0:v? -map [outa]" in " ".join(argv)


# --- Time: still image -> clip ----------------------------------------------

def test_still_image_detection():
    assert time_op.is_still_image(_media(audio=False, format_name="png_pipe"))
    assert time_op.is_still_image(_media(audio=False, format_name="image2"))
    assert not time_op.is_still_image(_media())  # a movie
    assert not time_op.is_still_image(_media(format_name="png_pipe"))  # has audio: not a still


def test_still_build_loops_for_duration():
    op = time_op.build({"mode": "still", "seconds": 4.0, "fps": 25}, _media(audio=False, format_name="png_pipe"), CAPS)
    argv = _argv_for(op, _media(audio=False, format_name="png_pipe"))
    assert argv[argv.index("-loop") + 1] == "1"
    assert argv.index("-loop") < argv.index("-i")  # must precede the input
    joined = " ".join(argv)
    assert "-t 4.0" in joined
    assert "-r 25" in joined
    assert "format=yuv420p" in joined
