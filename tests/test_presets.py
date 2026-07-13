from pathlib import Path

from ffx.models import HardwareCapabilities, MediaInfo, StreamInfo
from ffx.presets import estimate_presets, target_size_video_kbps

NO_HW = HardwareCapabilities(videotoolbox_available=False, hw_encoders=set(), hw_decoders=set())


def _media(*, video_bitrate: int | None = 5_000_000, codec_name: str = "h264", duration: float = 60.0) -> MediaInfo:
    video = StreamInfo(
        index=0, codec_type="video", codec_name=codec_name, width=1920, height=1080, bit_rate=video_bitrate,
    )
    return MediaInfo(
        path=Path("in.mp4"), format_name="mp4", format_long_name="MP4",
        duration=duration, size=1000, bit_rate=video_bitrate or 0, streams=[video],
    )


def test_no_tier_targets_more_than_the_source_ceiling():
    # Re-encoding a lossy source can't recover detail that isn't there -
    # every compression tier must sit at or below "Original quality",
    # never above it (the bug the fixed-absolute-kbps tiers used to have).
    rows = estimate_presets("h264", _media(), NO_HW)
    ceiling = next(r.target_video_kbps for r in rows if r.tier_name == "Original quality")
    for r in rows:
        assert r.target_video_kbps <= ceiling


def test_compression_tiers_are_fractions_of_the_ceiling():
    rows = estimate_presets("h264", _media(), NO_HW)
    ceiling = next(r for r in rows if r.tier_name == "Original quality")
    assert ceiling.fraction == 1.0

    balanced = next(r for r in rows if r.tier_name == "Balanced")
    assert balanced.fraction == 0.55
    assert balanced.target_video_kbps == round(ceiling.target_video_kbps * 0.55)


def test_less_efficient_target_codec_can_exceed_source_bitrate():
    # The one legitimate exception: switching to a *less* efficient codec
    # (e.g. H.264 -> MPEG-2) needs more bits to match perceived quality -
    # that's compensating for a weaker codec, not fabricating data.
    rows = estimate_presets("mpeg2", _media(codec_name="h264"), NO_HW)
    ceiling = next(r for r in rows if r.tier_name == "Original quality")
    assert ceiling.target_video_kbps > 5000


def test_falls_back_to_absolute_tiers_when_source_bitrate_unknown():
    media = _media(video_bitrate=None)
    media.bit_rate = 0
    rows = estimate_presets("h264", media, NO_HW)
    assert not any(r.tier_name == "Original quality" for r in rows)
    assert all(r.fraction is None for r in rows)
    tier_names = {r.tier_name for r in rows}
    assert tier_names == {"Light", "Balanced", "High", "Max"}


def test_target_size_video_kbps_basic_math():
    # 10 MB over 60s, minus 192kbps audio.
    result = target_size_video_kbps(10.0, 60.0, 192)
    expected_total_kbps = (10.0 * 1024 * 8) / 60.0
    assert result.video_kbps == round(expected_total_kbps - 192)
    assert result.feasible is True


def test_target_size_video_kbps_floors_and_flags_infeasible():
    # A tiny target over a long duration can't realistically be hit.
    result = target_size_video_kbps(1.0, 600.0, 192)
    assert result.video_kbps == 300
    assert result.feasible is False
