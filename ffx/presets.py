from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ffx.models import HardwareCapabilities, MediaInfo

# Target total bitrate (video+audio) per quality tier at 1080p, independent
# of source bitrate or codec - these get scaled by codec efficiency and
# source resolution below. Audio is assumed ~128kbps and subtracted to get
# the video-only target passed to the encoder.
_AUDIO_BITRATE_KBPS = 128

# Every tier below "Original quality" is a fraction of the source's own
# (codec-efficiency-adjusted) bitrate - never above it. Re-encoding a lossy
# source can't recover detail that isn't there, so a tier that targeted
# *more* bits than the source already has would just bloat the file for no
# real quality gain. This keeps every option on one real sliding scale from
# "as-is" down to "small", instead of a fixed absolute number that could
# land above the source for an already-compressed file.
_COMPRESSION_TIERS: list[tuple[str, float]] = [
    ("Light", 0.80),
    ("Balanced", 0.55),
    ("High", 0.35),
    ("Max", 0.20),
]

# Fallback absolute 1080p targets for the rare case ffprobe can't report any
# source bitrate at all - there's nothing to scale a percentage against, so
# these fall back to fixed numbers, ordered to match the tiers above (less
# compression -> more bits).
_FALLBACK_ABSOLUTE_KBPS: dict[str, int] = {
    "Light": 8000,
    "Balanced": 4000,
    "High": 2000,
    "Max": 1000,
}

# codec -> relative bits-per-pixel efficiency vs H.264 baseline (1.0).
# Lower means it needs less bitrate for the same perceived quality, so
# the estimated target bitrate is scaled down for more efficient codecs.
# Also used to scale the "Original quality" tier when the source and
# target codecs differ, so switching to a more efficient codec doesn't
# just copy the old bitrate straight over (that would waste space) and
# switching to a less efficient one doesn't quietly lose quality.
_CODEC_EFFICIENCY = {
    "h264": 1.0,
    "hevc": 0.65,
    "av1": 0.5,
    "vp9": 0.7,
    "mpeg2": 1.6,
}

_SOFTWARE_ENCODER = {
    "h264": "libx264",
    "hevc": "libx265",
    "av1": "libsvtav1",
    "vp9": "libvpx-vp9",
    "mpeg2": "mpeg2video",
}

# Only h264/hevc have a VideoToolbox hardware encoder on Apple Silicon today.
_HARDWARE_ENCODER = {
    "h264": "h264_videotoolbox",
    "hevc": "hevc_videotoolbox",
}

# Normalizes ffprobe's codec_name to the _CODEC_EFFICIENCY keys, for
# scaling the "Original quality" tier relative to what the source
# actually is.
_SOURCE_CODEC_NORMALIZE = {
    "h265": "hevc",
    "mpeg2video": "mpeg2",
    "vp8": "vp9",
}


@dataclass
class EncodePreset:
    tier_name: str
    codec: str
    engine: str  # "hardware" or "software"
    encoder_name: str
    target_video_kbps: int
    estimated_size_mb: float
    speed_note: str
    # Fraction of the source's own bitrate this tier targets (None for
    # "Original quality" and for the no-source-bitrate fallback tiers,
    # neither of which are expressed as a fraction) - not shown in the UI,
    # kept so the sliding-scale math (never above the source ceiling) is
    # directly checkable/testable rather than only implicit in the numbers.
    fraction: Optional[float] = None


@dataclass
class TargetSizeResult:
    video_kbps: int
    # False if the raw computed bitrate had to be floored - i.e. the
    # requested size is tighter than this duration can realistically hit.
    feasible: bool


def estimate_presets(
    codec: str, media: MediaInfo, hardware: HardwareCapabilities
) -> list[EncodePreset]:
    """Compute compression-tier rows for the codec the user already chose.

    Returns one row per (tier, engine) combination actually available on
    this machine for `codec`, so the caller can show them side by side
    with an estimated size and let the user pick with real tradeoffs in
    view, rather than presets that silently swap in a different codec.

    Every tier is derived from the source's own bitrate (adjusted for
    codec efficiency, so switching to a more/less efficient codec doesn't
    just copy the number over) and capped at it - "Original quality" is
    the ceiling, everything else is a fraction of that ceiling. Only when
    the source's bitrate can't be determined at all does this fall back
    to fixed absolute targets.
    """
    video = media.primary_video
    height = video.height if video and video.height else 1080
    duration = media.duration or 0.0
    efficiency = _CODEC_EFFICIENCY.get(codec, 1.0)

    rows: list[EncodePreset] = []
    original_kbps = _source_video_kbps(media)

    if original_kbps:
        source_codec = _SOURCE_CODEC_NORMALIZE.get(video.codec_name, video.codec_name) if video else None
        source_efficiency = _CODEC_EFFICIENCY.get(source_codec, 1.0)
        ceiling_kbps = original_kbps * (efficiency / source_efficiency)

        rows += _rows_for_tier(
            "Original quality", codec, max(300, round(ceiling_kbps)), duration, hardware, "matches source", fraction=1.0
        )
        for tier_name, fraction in _COMPRESSION_TIERS:
            video_kbps = max(300, round(ceiling_kbps * fraction))
            rows += _rows_for_tier(tier_name, codec, video_kbps, duration, hardware, None, fraction=fraction)
    else:
        # Nothing to scale a percentage against - fall back to fixed
        # targets, still scaled down for small source resolutions so a
        # low-res source isn't inflated to a 1080p-sized bitrate budget.
        scale_factor = min(1.0, height / 1080) if height else 1.0
        for tier_name, kbps_1080p in _FALLBACK_ABSOLUTE_KBPS.items():
            video_kbps = max(300, round(kbps_1080p * efficiency * scale_factor))
            rows += _rows_for_tier(tier_name, codec, video_kbps, duration, hardware, None, fraction=None)

    return rows


def target_size_video_kbps(target_mb: float, duration: float, audio_kbps: float) -> TargetSizeResult:
    """Video bitrate needed to land the whole file at `target_mb`, given
    the audio bitrate that will actually be used (not a guess - the caller
    passes the real bitrate of whatever audio codec was already chosen).

    Floored at 300kbps; when the raw computation lands below that, the
    request genuinely can't be met at this duration, so `feasible=False`
    tells the caller to warn rather than silently promise a size it can't
    hit.
    """
    if duration <= 0:
        return TargetSizeResult(video_kbps=300, feasible=False)
    total_kbps = (target_mb * 1024 * 8) / duration
    raw = round(total_kbps - audio_kbps)
    return TargetSizeResult(video_kbps=max(300, raw), feasible=raw >= 300)


def _rows_for_tier(
    tier_name: str,
    codec: str,
    video_kbps: int,
    duration: float,
    hardware: HardwareCapabilities,
    note_override: str | None,
    fraction: Optional[float],
) -> list[EncodePreset]:
    rows = [
        _make_row(
            tier_name,
            codec,
            "software",
            _SOFTWARE_ENCODER[codec],
            video_kbps,
            duration,
            note_override or "smaller, slower",
            fraction,
        )
    ]
    hw_encoder = _HARDWARE_ENCODER.get(codec)
    if hw_encoder and hardware.has_encoder(hw_encoder):
        rows.append(
            _make_row(
                tier_name,
                codec,
                "hardware",
                hw_encoder,
                video_kbps,
                duration,
                note_override or "faster (hardware)",
                fraction,
            )
        )
    return rows


def _source_video_kbps(media: MediaInfo) -> float | None:
    video = media.primary_video
    if video and video.bit_rate:
        return video.bit_rate / 1000
    if media.bit_rate and media.duration:
        estimate = media.bit_rate / 1000 - _AUDIO_BITRATE_KBPS
        return estimate if estimate > 0 else None
    return None


def estimate_fixed_bitrate_size(base_kbps_1080p30: float, media: MediaInfo) -> float:
    """Estimate output size (MB) for a profile-based codec (ProRes, DNxHR).

    These codecs don't take a quality target - the profile itself fixes
    an approximate data rate. `base_kbps_1080p30` is that profile's
    well-known rate at 1920x1080/30fps; scaled by actual resolution and
    frame rate (uncapped, since these formats are used at native
    resolution rather than a delivery target) to give a ballpark size.
    """
    video = media.primary_video
    width = video.width if video and video.width else 1920
    height = video.height if video and video.height else 1080
    fps = (video.frame_rate if video else None) or 30.0
    duration = media.duration or 0.0

    resolution_factor = (width * height) / (1920 * 1080)
    fps_factor = fps / 30.0
    kbps = base_kbps_1080p30 * resolution_factor * fps_factor
    return round((kbps * duration) / 8 / 1024, 1)


def humanize_size(size_mb: float) -> str:
    """Format an estimated size in MB as a friendlier KB/MB/GB string."""
    if size_mb >= 1024:
        return f"{size_mb / 1024:.2f} GB"
    if size_mb >= 1:
        return f"{size_mb:.1f} MB"
    return f"{max(size_mb * 1024, 1):.0f} KB"


def _make_row(
    tier_name: str,
    codec: str,
    engine: str,
    encoder_name: str,
    video_kbps: int,
    duration: float,
    speed_note: str,
    fraction: Optional[float],
) -> EncodePreset:
    total_kbps = video_kbps + _AUDIO_BITRATE_KBPS
    estimated_size_mb = (total_kbps * duration) / 8 / 1024
    return EncodePreset(
        tier_name=tier_name,
        codec=codec,
        engine=engine,
        encoder_name=encoder_name,
        target_video_kbps=video_kbps,
        estimated_size_mb=round(estimated_size_mb, 1),
        speed_note=speed_note,
        fraction=fraction,
    )
