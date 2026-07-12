from __future__ import annotations

from dataclasses import dataclass

from ffx.models import HardwareCapabilities, MediaInfo

# Target total bitrate (video+audio) per quality tier, independent of
# source bitrate - these are the tiers shown to the user for "compress to
# a sensible size" workflows. Audio is assumed ~128kbps and subtracted to
# get the video-only target passed to the encoder.
_AUDIO_BITRATE_KBPS = 128

_QUALITY_TIERS: dict[str, dict[str, int]] = {
    # name -> {resolution_cap_height, total_kbps_per_1080p}
    "Small (web share)": {"height_cap": 720, "kbps_1080p": 2500},
    "Balanced": {"height_cap": 1080, "kbps_1080p": 5000},
    "High quality (archive)": {"height_cap": 2160, "kbps_1080p": 10000},
}

# codec -> relative bits-per-pixel efficiency vs H.264 baseline (1.0).
# Lower means it needs less bitrate for the same perceived quality, so
# the estimated target bitrate is scaled down for more efficient codecs.
_CODEC_EFFICIENCY = {
    "h264": 1.0,
    "hevc": 0.65,
    "av1": 0.55,
    "vp9": 0.7,
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


def estimate_presets(
    media: MediaInfo, hardware: HardwareCapabilities
) -> list[EncodePreset]:
    """Compute HW + SW preset rows for each quality tier.

    Returns one row per (tier, engine) combination that's actually
    available on this machine, so the caller can show them side by side
    with an estimated size and let the user pick with real tradeoffs
    in view rather than a hidden default.
    """
    video = media.primary_video
    height = video.height if video and video.height else 1080
    duration = media.duration or 0.0

    rows: list[EncodePreset] = []
    for tier_name, tier in _QUALITY_TIERS.items():
        codec = "hevc" if tier["height_cap"] >= 2160 else "h264"
        base_kbps = tier["kbps_1080p"] * _CODEC_EFFICIENCY.get(codec, 1.0)
        # Scale target bitrate for source resolutions well below 1080p so
        # small sources aren't inflated to a 1080p-sized bitrate budget.
        scale_factor = min(1.0, height / 1080) if height else 1.0
        video_kbps = max(300, round(base_kbps * scale_factor))

        rows.append(
            _make_row(
                tier_name,
                codec,
                "software",
                _software_encoder(codec),
                video_kbps,
                duration,
                "slower, best compression",
            )
        )
        if hardware.has_encoder(f"{codec}_videotoolbox"):
            rows.append(
                _make_row(
                    tier_name,
                    codec,
                    "hardware",
                    f"{codec}_videotoolbox",
                    video_kbps,
                    duration,
                    "fast, uses Apple Silicon media engine",
                )
            )
    return rows


def _software_encoder(codec: str) -> str:
    return {"h264": "libx264", "hevc": "libx265", "av1": "libsvtav1", "vp9": "libvpx-vp9"}[codec]


def _make_row(
    tier_name: str,
    codec: str,
    engine: str,
    encoder_name: str,
    video_kbps: int,
    duration: float,
    speed_note: str,
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
    )
