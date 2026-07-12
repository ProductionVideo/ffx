from __future__ import annotations

from dataclasses import dataclass

from ffx.models import HardwareCapabilities, MediaInfo

# Target total bitrate (video+audio) per quality tier at 1080p, independent
# of source bitrate or codec - these get scaled by codec efficiency and
# source resolution below. Audio is assumed ~128kbps and subtracted to get
# the video-only target passed to the encoder.
_AUDIO_BITRATE_KBPS = 128

_QUALITY_TIERS: dict[str, int] = {
    "Small (web share)": 2500,
    "Balanced": 5000,
    "High quality (archive)": 10000,
}

# codec -> relative bits-per-pixel efficiency vs H.264 baseline (1.0).
# Lower means it needs less bitrate for the same perceived quality, so
# the estimated target bitrate is scaled down for more efficient codecs.
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
    codec: str, media: MediaInfo, hardware: HardwareCapabilities
) -> list[EncodePreset]:
    """Compute compression-tier rows for the codec the user already chose.

    Returns one row per (tier, engine) combination actually available on
    this machine for `codec`, so the caller can show them side by side
    with an estimated size and let the user pick with real tradeoffs in
    view, rather than presets that silently swap in a different codec.
    """
    video = media.primary_video
    height = video.height if video and video.height else 1080
    duration = media.duration or 0.0
    efficiency = _CODEC_EFFICIENCY.get(codec, 1.0)
    # Scale target bitrate down for source resolutions well below 1080p so
    # small sources aren't inflated to a 1080p-sized bitrate budget.
    scale_factor = min(1.0, height / 1080) if height else 1.0

    rows: list[EncodePreset] = []
    for tier_name, kbps_1080p in _QUALITY_TIERS.items():
        video_kbps = max(300, round(kbps_1080p * efficiency * scale_factor))

        rows.append(
            _make_row(
                tier_name,
                codec,
                "software",
                _SOFTWARE_ENCODER[codec],
                video_kbps,
                duration,
                "slower, best compression",
            )
        )
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
                    "fast, uses Apple Silicon media engine",
                )
            )
    return rows


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
