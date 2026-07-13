from __future__ import annotations

from ffx import presets as preset_calc
from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings
from ffx.ui import prompts
from ffx.ui.theme import console

name = "convert"
display_name = "Convert"
description = "Swap codec, container, or both"

# "Standard" codecs share one quality mechanism: an engine choice (software
# vs VideoToolbox hardware, where available) and either a calculated
# compression-preset tier or a manually entered quality value. ProRes and
# DNxHR are profile-based (the profile *is* the quality tier) and are
# handled separately below.
_VIDEO_CODECS = {
    "h264": {"sw": "libx264", "hw": "h264_videotoolbox"},
    "hevc": {"sw": "libx265", "hw": "hevc_videotoolbox"},
    "av1": {"sw": "libsvtav1", "hw": None},
    "vp9": {"sw": "libvpx-vp9", "hw": None},
    "mpeg2": {"sw": "mpeg2video", "hw": None},
}

_MANUAL_QUALITY_FLAG = {
    "h264": "-crf",
    "hevc": "-crf",
    "av1": "-crf",
    "vp9": "-crf",
    "mpeg2": "-q:v",
}
_MANUAL_QUALITY_DEFAULT = {
    "h264": "23",
    "hevc": "23",
    "av1": "32",
    "vp9": "32",
    "mpeg2": "4",
}
_MANUAL_QUALITY_HINT = {
    "h264": "CRF, lower = higher quality/larger file (~18-28 typical)",
    "hevc": "CRF, lower = higher quality/larger file (~18-28 typical)",
    "av1": "CRF, lower = higher quality/larger file (~24-40 typical)",
    "vp9": "CRF, lower = higher quality/larger file (~24-40 typical)",
    "mpeg2": "qscale, lower = higher quality/larger file (1-31, ~2-6 typical)",
}

_DEFAULT_CONTAINER = {
    "h264": "mp4",
    "hevc": "mp4",
    "av1": "webm",
    "vp9": "webm",
    "prores": "mov",
    "dnxhr": "mov",
    "hap": "mov",
    "mpeg2": "mov",
    "copy_v": "mp4",
}
_DEFAULT_AUDIO = {
    "prores": "pcm",
    "dnxhr": "pcm",
    "hap": "pcm",
}

# Which containers ffmpeg can actually mux each codec into on this build -
# verified empirically (encode + ffprobe read-back), not assumed. A codec
# writing "successfully" into an incompatible container can still produce
# an unreadable file, so this gates the menu rather than just warning.
_CONTAINER_COMPAT = {
    "h264": {"mp4", "mov", "mkv", "avi", "ts", "mxf"},
    "hevc": {"mp4", "mov", "mkv", "avi", "ts"},
    "av1": {"mp4", "mkv", "webm", "avi"},
    "vp9": {"mp4", "mkv", "webm", "avi"},
    "prores": {"mov", "mkv", "avi", "mxf"},
    "dnxhr": {"mov", "mkv", "avi", "mxf"},
    # MOV only: it's what every HAP-playing app (Resolume, TouchDesigner,
    # Millumin) actually reads - not verified wider on this build because
    # the local ffmpeg can't encode HAP at all.
    "hap": {"mov"},
    "mpeg2": {"mp4", "mov", "mkv", "avi", "ts", "mxf"},
}
# Normalize ffprobe's codec_name to the keys above, for filtering the
# container list on a "Copy (no re-encode)" pick, where we don't choose
# the codec ourselves - it's whatever the source already is.
_SOURCE_CODEC_ALIAS = {"mpeg2video": "mpeg2", "dnxhd": "dnxhr"}

_PRORES_PROFILES = [("Proxy", "0"), ("LT", "1"), ("Standard 422", "2"), ("422 HQ", "3")]
# Apple's approximate published data rates at 1920x1080/29.97fps (Mbit/s),
# used only to show a ballpark output size - ProRes has no quality target,
# the profile itself fixes the rate.
_PRORES_KBPS_1080P30 = {"0": 45_000, "1": 102_000, "2": 147_000, "3": 220_000}

_DNXHR_PROFILES = [
    ("LQ — offline edit", "dnxhr_lq"),
    ("SQ — standard", "dnxhr_sq"),
    ("HQ — high quality", "dnxhr_hq"),
    ("HQX — 10-bit", "dnxhr_hqx"),
    ("444 — full chroma, 10-bit", "dnxhr_444"),
]
_DNXHR_PIXFMT = {
    "dnxhr_lq": "yuv422p",
    "dnxhr_sq": "yuv422p",
    "dnxhr_hq": "yuv422p",
    "dnxhr_hqx": "yuv422p10le",
    "dnxhr_444": "yuv444p10le",
}
# Avid's approximate published data rates at 1920x1080/29.97fps (Mbit/s).
_DNXHR_KBPS_1080P30 = {
    "dnxhr_lq": 36_000,
    "dnxhr_sq": 75_000,
    "dnxhr_hq": 145_000,
    "dnxhr_hqx": 220_000,
    "dnxhr_444": 365_000,
}

# HAP (Vidvox) - GPU-decoded DXT textures for VJ/media-server playback
# (Resolume, TouchDesigner, Millumin). Quality is fixed by the flavour,
# like ProRes profiles; the ecosystem expects .mov. Rough data rates at
# 1920x1080/30fps: DXT1 is 0.5 byte/px (Hap), DXT5 1 byte/px (Alpha/Q),
# snappy then shaves roughly a third - shown only as ballpark sizes.
_HAP_FORMATS = [
    ("Hap — standard, lightest to play back", "hap"),
    ("Hap Alpha — carries transparency", "hap_alpha"),
    ("Hap Q — higher quality, larger", "hap_q"),
]
_HAP_KBPS_1080P30 = {"hap": 150_000, "hap_alpha": 300_000, "hap_q": 300_000}


def hap_unavailable_reason(hardware: HardwareCapabilities) -> str | None:
    """The hap encoder is compile-time optional (needs libsnappy) and
    missing from Homebrew's default ffmpeg formula - same situation as
    Text's drawtext, surfaced on the menu entry the same way."""
    if hardware.encoders and not hardware.can_encode("hap"):
        return "this ffmpeg can't encode HAP — brew install ffmpeg-full"
    return None


_CONTAINER_LABELS = [
    ("MP4", "mp4"),
    ("MOV", "mov"),
    ("MKV", "mkv"),
    ("WebM", "webm"),
    ("MXF", "mxf"),
    ("AVI", "avi"),
    ("MPEG-TS", "ts"),
]

_AUDIO_CODECS = {
    "aac": {"encoder": "aac", "bitrate_k": 192},
    "opus": {"encoder": "libopus", "bitrate_k": 128},
    "mp3": {"encoder": "libmp3lame", "bitrate_k": 192},
    "ac3": {"encoder": "ac3", "bitrate_k": 192},
    "flac": {"encoder": "flac", "bitrate_k": None},
    "pcm": {"encoder": "pcm_s16le", "bitrate_k": None},
    "copy": {"encoder": "copy", "bitrate_k": None},
}


def tui_form(media: MediaInfo, hardware: HardwareCapabilities):
    """The single-screen Textual form used instead of prompt() when the
    full-screen app is live - same params dict out, one screen instead of
    six sequential questions."""
    from ffx.tui.forms import ConvertScreen

    return ConvertScreen(media, hardware)


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict | None:
    # Codec first, then everything else defaults sensibly around it (right
    # container, right audio codec, right engine/profile) so switching
    # codec is the one real decision - every other prompt is an Enter to
    # accept the default, or an arrow-key away from overriding it.
    hap_reason = hap_unavailable_reason(hardware)
    hap_label = "HAP (VJ / media servers)" + (f"  [unavailable: {hap_reason}]" if hap_reason else "")
    vcodec = prompts.choose(
        "Video codec:",
        [
            ("H.264", "h264"),
            ("H.265 / HEVC", "hevc"),
            ("AV1", "av1"),
            ("VP9", "vp9"),
            ("ProRes", "prores"),
            ("DNxHR (Avid)", "dnxhr"),
            (hap_label, "hap"),
            ("MPEG-2", "mpeg2"),
            ("Copy (no re-encode)", "copy_v"),
        ],
        default="h264",
    )
    if vcodec == "hap" and hap_reason:
        console.print(
            "This ffmpeg build can't encode HAP (the encoder needs libsnappy). "
            "`brew install ffmpeg-full` includes it.",
            style="ffx.error",
        )
        return None
    container_choices, container_default = container_options(vcodec, media)
    container = prompts.choose(
        "Target container:",
        container_choices,
        default=container_default,
    )

    acodec = prompts.choose(
        "Audio codec:",
        [
            ("AAC", "aac"),
            ("Opus", "opus"),
            ("MP3", "mp3"),
            ("AC-3", "ac3"),
            ("FLAC", "flac"),
            ("PCM / WAV", "pcm"),
            ("Copy (no re-encode)", "copy"),
        ],
        default=_DEFAULT_AUDIO.get(vcodec, "copy"),
    )

    params: dict = {"container": container, "vcodec": vcodec, "acodec": acodec}

    if vcodec == "copy_v":
        pass
    elif vcodec == "prores":
        params["prores_profile"] = prompts.choose(
            "ProRes profile:", _profile_choices(_PRORES_PROFILES, _PRORES_KBPS_1080P30, media), default="3"
        )
        use_hw = hardware.has_encoder("prores_videotoolbox") and prompts.ask_confirm(
            "Use hardware encoding?", default=True, hint="VideoToolbox — fast, uses the media engine."
        )
        params["engine"] = "hardware" if use_hw else "software"
    elif vcodec == "dnxhr":
        params["dnxhr_profile"] = prompts.choose(
            "DNxHR profile:",
            _profile_choices(_DNXHR_PROFILES, _DNXHR_KBPS_1080P30, media),
            default="dnxhr_hq",
        )
    elif vcodec == "hap":
        params["hap_format"] = prompts.choose(
            "HAP flavour:",
            _profile_choices(_HAP_FORMATS, _HAP_KBPS_1080P30, media),
            default="hap",
        )
    else:
        engine = _choose_engine(vcodec, hardware)
        params["engine"] = engine
        params.update(_choose_quality(vcodec, engine, media, hardware, acodec))
        if engine == "software" and params.get("quality_mode") in ("bitrate", "target_size"):
            params["two_pass"] = prompts.ask_confirm(
                "Two-pass encode?",
                default=params.get("quality_mode") == "target_size",
                hint="Slower (encodes twice) but lands much closer to the target.",
            )

    return params


def container_options(vcodec: str, media: MediaInfo) -> tuple[list[tuple[str, str]], str]:
    """(choices, default) for the target container, filtered to what this
    codec can actually be muxed into. Shared by both UIs."""
    compat_key = _compat_key_for(vcodec, media)
    compatible = _CONTAINER_COMPAT.get(compat_key)
    choices = [c for c in _CONTAINER_LABELS if compatible is None or c[1] in compatible]
    preferred = _DEFAULT_CONTAINER[vcodec]
    default = preferred if preferred in {key for _, key in choices} else choices[0][1]
    return choices, default


def engine_options(vcodec: str, hardware: HardwareCapabilities) -> tuple[list[tuple[str, str]], str]:
    """(choices, default) for the encoder engine of a standard codec."""
    codec_info = _VIDEO_CODECS[vcodec]
    options = [("Software — best quality, slower", "software")]
    default = "software"
    if codec_info["hw"] and hardware.has_encoder(codec_info["hw"]):
        options.insert(0, ("Hardware — fast (Apple Silicon)", "hardware"))
        default = "hardware"
    return options, default


def audio_kbps_for(acodec: str, media: MediaInfo) -> float | None:
    """The predictable audio bitrate a size target can budget around, or
    None when there isn't one (FLAC/PCM are content/format dependent)."""
    if acodec == "copy":
        audio = media.primary_audio
        return (audio.bit_rate / 1000) if audio and audio.bit_rate else None
    return _AUDIO_CODECS[acodec]["bitrate_k"]


def quality_options(
    vcodec: str, engine: str, media: MediaInfo, hardware: HardwareCapabilities, acodec: str
) -> tuple[list, list[tuple[str, str]], str]:
    """(tier rows, (label, token) choices, default token) for the quality
    menu of a standard codec. Tokens: "tier:<i>", "target", "manual"."""
    rows = [r for r in preset_calc.estimate_presets(vcodec, media, hardware) if r.engine == engine]
    options = [
        (f"{r.tier_name} — ~{preset_calc.humanize_size(r.estimated_size_mb)}, {r.speed_note}", f"tier:{i}")
        for i, r in enumerate(rows)
    ]
    if audio_kbps_for(acodec, media) is not None:
        options.append(("Target size... (enter an exact MB)", "target"))
    options.append(("Manual", "manual"))
    default = next((f"tier:{i}" for i, r in enumerate(rows) if r.tier_name == "Balanced"), "manual")
    return rows, options, default


def _compat_key_for(vcodec: str, media: MediaInfo) -> str | None:
    """Which _CONTAINER_COMPAT key applies, or None if unknown (don't filter)."""
    if vcodec != "copy_v":
        return vcodec
    source = media.primary_video.codec_name if media.primary_video else None
    if not source:
        return None
    source = _SOURCE_CODEC_ALIAS.get(source, source)
    return source if source in _CONTAINER_COMPAT else None


def _profile_choices(
    profiles: list[tuple[str, str]], kbps_1080p30: dict[str, int], media: MediaInfo
) -> list[tuple[str, str]]:
    """Annotate profile labels with an estimated output size."""
    choices = []
    for label, key in profiles:
        size_mb = preset_calc.estimate_fixed_bitrate_size(kbps_1080p30[key], media)
        choices.append((f"{label} — ~{preset_calc.humanize_size(size_mb)}", key))
    return choices


def _choose_engine(vcodec: str, hardware: HardwareCapabilities) -> str:
    options, default = engine_options(vcodec, hardware)
    if len(options) == 1:
        return options[0][1]
    return prompts.choose(
        "Encoder:", options, default=default, hint="Software usually compresses better; hardware is faster."
    )


def _choose_quality(
    vcodec: str, engine: str, media: MediaInfo, hardware: HardwareCapabilities, acodec: str
) -> dict:
    """One menu: calculated compression tiers, an exact target size, and a
    manual escape hatch - compression is a single, clearly labeled choice
    here, defaulted to "Balanced".
    """
    rows, options, default_token = quality_options(vcodec, engine, media, hardware, acodec)
    token = prompts.choose(
        "Quality:", options, default=default_token, hint="Sizes are estimates, not guarantees."
    )

    if token == "target":
        target_mb = prompts.ask_float(
            "Target size MB (1GB = 1000MB):", default=25.0, min_allowed=0.1, hint="ffx works out the bitrate needed to hit this."
        )
        result = preset_calc.target_size_video_kbps(
            target_mb, media.duration or 0.0, audio_kbps_for(acodec, media)
        )
        if not result.feasible:
            console.print(
                f"Heads up: {target_mb:g} MB over {media.duration:.0f}s is a very tight budget — "
                "the output will likely come in larger than that.",
                style="ffx.warn",
            )
        return {"quality_mode": "target_size", "video_kbps": result.video_kbps, "target_size_mb": target_mb}

    if token.startswith("tier:"):
        chosen = rows[int(token.split(":")[1])]
        return {"quality_mode": "bitrate", "video_kbps": chosen.target_video_kbps}

    if engine == "hardware":
        quality = prompts.ask_int("Quality (1-100, higher = better, larger):", default=65, min_allowed=1, max_allowed=100)
        return {"quality_mode": "hw_quality", "hw_quality": quality}

    value = prompts.ask_int(
        f"Manual quality ({_MANUAL_QUALITY_HINT[vcodec]}):",
        default=int(_MANUAL_QUALITY_DEFAULT[vcodec]),
    )
    return {"quality_mode": "manual", "manual_value": value}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    output_args: list[str] = []
    video_filter: list[str] = []
    vcodec = params.get("vcodec")

    if vcodec == "copy_v":
        output_args += ["-c:v", "copy"]
    elif vcodec == "hap":
        # -chunks 8: split each frame's texture for parallel snappy decode
        # on playback (the whole point of HAP is cheap playback).
        output_args += ["-c:v", "hap", "-format", params.get("hap_format", "hap"), "-chunks", "8"]
        video = media.primary_video
        if video and video.width and video.height and (video.width % 4 or video.height % 4):
            # DXT compresses in 4x4 texel blocks - snap odd dimensions down
            # to the nearest multiple of 4 rather than let the encode fail.
            video_filter.append("scale=trunc(iw/4)*4:trunc(ih/4)*4")
    elif vcodec == "prores":
        engine = params.get("engine", "software")
        encoder = "prores_videotoolbox" if engine == "hardware" else "prores_ks"
        output_args += ["-c:v", encoder, "-profile:v", params.get("prores_profile", "2")]
    elif vcodec == "dnxhr":
        profile = params.get("dnxhr_profile", "dnxhr_hq")
        output_args += [
            "-c:v", "dnxhd",
            "-profile:v", profile,
            "-pix_fmt", _DNXHR_PIXFMT[profile],
        ]
    elif vcodec:
        codec_info = _VIDEO_CODECS[vcodec]
        engine = params.get("engine", "software")
        encoder = codec_info["hw"] if engine == "hardware" and codec_info["hw"] else codec_info["sw"]
        output_args += ["-c:v", encoder]
        output_args += _quality_args(vcodec, engine, params)

    acodec = params.get("acodec", "aac")
    audio_info = _AUDIO_CODECS[acodec]
    non_video_output_args = ["-c:a", audio_info["encoder"]]
    if audio_info["bitrate_k"]:
        non_video_output_args += ["-b:a", f"{audio_info['bitrate_k']}k"]

    description = f"Convert to {params.get('container', 'mp4').upper()}"
    if params.get("quality_mode") == "target_size":
        description += f", target ~{params.get('target_size_mb'):g} MB"
    if params.get("two_pass"):
        description += " (2-pass)"

    return OperationSettings(
        name=name,
        display_name=display_name,
        description=description,
        video_filter=video_filter,
        output_args=output_args,
        non_video_output_args=non_video_output_args,
        two_pass=bool(params.get("two_pass", False)),
        serializable={"container": params.get("container", "mp4")},
    )


def _quality_args(vcodec: str, engine: str, params: dict) -> list[str]:
    if params.get("quality_mode") == "bitrate":
        return ["-b:v", f"{params['video_kbps']}k"]
    if params.get("quality_mode") == "hw_quality" or engine == "hardware":
        return ["-q:v", str(params.get("hw_quality", 65))]
    value = str(params.get("manual_value", _MANUAL_QUALITY_DEFAULT[vcodec]))
    flag = _MANUAL_QUALITY_FLAG[vcodec]
    if vcodec == "vp9":
        return [flag, value, "-b:v", "0"]
    return [flag, value]


def output_extension(params: dict) -> str:
    return params.get("container", "mp4")
