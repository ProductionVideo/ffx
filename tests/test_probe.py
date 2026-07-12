import json
import subprocess
from pathlib import Path

from ffx import probe

_SAMPLE_FFPROBE_JSON = {
    "streams": [
        {
            "index": 0,
            "codec_name": "h264",
            "codec_long_name": "H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10",
            "profile": "High",
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "pix_fmt": "yuv420p",
            "r_frame_rate": "30/1",
            "avg_frame_rate": "30/1",
            "bit_rate": "5000000",
            "duration": "10.000000",
            "bits_per_raw_sample": "8",
            "tags": {"language": "und"},
        },
        {
            "index": 1,
            "codec_name": "aac",
            "codec_long_name": "AAC (Advanced Audio Coding)",
            "codec_type": "audio",
            "channels": 2,
            "channel_layout": "stereo",
            "sample_rate": "48000",
            "bit_rate": "192000",
            "duration": "10.000000",
            "tags": {},
        },
    ],
    "format": {
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "format_long_name": "QuickTime / MOV",
        "duration": "10.000000",
        "size": "6500000",
        "bit_rate": "5200000",
        "tags": {"title": "Sample"},
    },
}


def test_probe_parses_ffprobe_json(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        class Result:
            returncode = 0
            stdout = json.dumps(_SAMPLE_FFPROBE_JSON)
            stderr = ""

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    media = probe.probe(Path("sample.mov"))

    assert media.duration == 10.0
    assert media.size == 6500000
    assert media.tags["title"] == "Sample"

    video = media.primary_video
    assert video is not None
    assert video.width == 1920 and video.height == 1080
    assert video.frame_rate == 30.0
    assert video.bit_depth == 8

    audio = media.primary_audio
    assert audio is not None
    assert audio.channels == 2
    assert audio.sample_rate == 48000


def test_probe_raises_on_nonzero_exit(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "No such file or directory"

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    try:
        probe.probe(Path("missing.mov"))
        assert False, "expected ProbeError"
    except probe.ProbeError as exc:
        assert "No such file" in str(exc)
