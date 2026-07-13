from pathlib import Path

from ffx.models import HardwareCapabilities, MediaInfo, StreamInfo
from ffx.operations import convert

NO_HAP = HardwareCapabilities(
    videotoolbox_available=False, hw_encoders=set(), hw_decoders=set(),
    encoders={"libx264", "aac"},
)
WITH_HAP = HardwareCapabilities(
    videotoolbox_available=False, hw_encoders=set(), hw_decoders=set(),
    encoders={"libx264", "aac", "hap"},
)
UNKNOWN = HardwareCapabilities(
    videotoolbox_available=False, hw_encoders=set(), hw_decoders=set(),
)


def _media(width=1920, height=1080) -> MediaInfo:
    video = StreamInfo(index=0, codec_type="video", codec_name="h264", width=width, height=height)
    return MediaInfo(
        path=Path("in.mp4"), format_name="mp4", format_long_name="MP4",
        duration=10.0, size=1000, bit_rate=5_000_000, streams=[video],
    )


def test_hap_build_args():
    op = convert.build({"vcodec": "hap", "hap_format": "hap_q", "container": "mov", "acodec": "pcm"}, _media(), WITH_HAP)
    joined = " ".join(op.output_args)
    assert "-c:v hap" in joined
    assert "-format hap_q" in joined
    assert "-chunks 8" in joined
    assert op.video_filter == []


def test_hap_snaps_odd_dimensions_to_multiple_of_four():
    op = convert.build({"vcodec": "hap", "container": "mov", "acodec": "pcm"}, _media(1918, 1079), WITH_HAP)
    assert op.video_filter == ["scale=trunc(iw/4)*4:trunc(ih/4)*4"]


def test_hap_unavailable_reason_gates_on_encoder_set():
    assert convert.hap_unavailable_reason(NO_HAP) is not None
    assert convert.hap_unavailable_reason(WITH_HAP) is None
    # An empty encoder set means detection failed (or a hand-built caps in
    # older tests) - don't claim unavailability we haven't established.
    assert convert.hap_unavailable_reason(UNKNOWN) is None


def test_hap_defaults_mov_container_and_pcm_audio():
    assert convert._DEFAULT_CONTAINER["hap"] == "mov"
    assert convert._DEFAULT_AUDIO["hap"] == "pcm"
    assert convert._CONTAINER_COMPAT["hap"] == {"mov"}
