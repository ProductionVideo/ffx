from __future__ import annotations

from ffx import presets as preset_calc
from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings, Preset
from ffx.ui import prompts

name = "convert"
display_name = "Convert"
description = "Change container and/or codecs, or compress to a target size"

_VIDEO_CODECS = {
    "h264": {"sw": "libx264", "hw": "h264_videotoolbox"},
    "hevc": {"sw": "libx265", "hw": "hevc_videotoolbox"},
    "av1": {"sw": "libsvtav1", "hw": None},
    "vp9": {"sw": "libvpx-vp9", "hw": None},
}

_AUDIO_CODECS = {
    "aac": {"encoder": "aac", "bitrate_k": 192},
    "opus": {"encoder": "libopus", "bitrate_k": 128},
    "mp3": {"encoder": "libmp3lame", "bitrate_k": 192},
    "ac3": {"encoder": "ac3", "bitrate_k": 192},
    "flac": {"encoder": "flac", "bitrate_k": None},
    "pcm": {"encoder": "pcm_s16le", "bitrate_k": None},
    "copy": {"encoder": "copy", "bitrate_k": None},
}

PRESETS = [
    Preset(
        "Web-friendly MP4",
        "H.264 + AAC, plays everywhere",
        {
            "container": "mp4",
            "vcodec": "h264",
            "engine": "software",
            "quality_mode": "crf",
            "crf": 20,
            "acodec": "aac",
        },
    ),
    Preset(
        "Small archive (HEVC/MKV)",
        "H.265 in MKV, noticeably smaller files",
        {
            "container": "mkv",
            "vcodec": "hevc",
            "engine": "software",
            "quality_mode": "crf",
            "crf": 24,
            "acodec": "aac",
        },
    ),
    Preset(
        "Editing master (ProRes 422 HQ)",
        "MOV, VideoToolbox ProRes for editing",
        {
            "container": "mov",
            "vcodec": "prores",
            "engine": "hardware",
            "prores_profile": "3",
            "acodec": "pcm",
        },
    ),
    Preset(
        "Web AV1 (WebM)",
        "Best compression for modern web delivery",
        {
            "container": "webm",
            "vcodec": "av1",
            "engine": "software",
            "quality_mode": "crf",
            "crf": 32,
            "acodec": "opus",
        },
    ),
]


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    preset = prompts.choose_preset(PRESETS, message="Convert — choose a preset:")
    if preset is not None:
        return dict(preset.values)

    container = prompts.choose(
        "Target container:",
        [
            ("MP4", "mp4"),
            ("MOV", "mov"),
            ("MKV", "mkv"),
            ("WebM", "webm"),
            ("MXF", "mxf"),
            ("AVI", "avi"),
            ("MPEG-TS", "ts"),
        ],
    )
    vcodec = prompts.choose(
        "Video codec:",
        [
            ("H.264", "h264"),
            ("H.265 / HEVC", "hevc"),
            ("ProRes", "prores"),
            ("AV1", "av1"),
            ("VP9", "vp9"),
            ("Copy (no re-encode)", "copy_v"),
        ],
    )

    params: dict = {"container": container, "vcodec": vcodec}

    if vcodec == "copy_v":
        pass
    elif vcodec == "prores":
        profile = prompts.choose(
            "ProRes profile:",
            [("Proxy", "0"), ("LT", "1"), ("Standard 422", "2"), ("422 HQ", "3")],
        )
        use_hw = hardware.has_encoder("prores_videotoolbox") and prompts.ask_confirm(
            "Use VideoToolbox hardware ProRes encoder?", default=True
        )
        params.update({"prores_profile": profile, "engine": "hardware" if use_hw else "software"})
    else:
        engine = _choose_engine(vcodec, hardware)
        params["engine"] = engine
        params.update(_choose_quality(vcodec, engine, media, hardware))

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
    )
    params["acodec"] = acodec
    return params


def _choose_engine(vcodec: str, hardware: HardwareCapabilities) -> str:
    codec_info = _VIDEO_CODECS[vcodec]
    options = [("Software (best quality/compression, slower)", "software")]
    if codec_info["hw"] and hardware.has_encoder(codec_info["hw"]):
        options.insert(0, ("Hardware / VideoToolbox (fast, uses media engine)", "hardware"))
    if len(options) == 1:
        return options[0][1]
    return prompts.choose("Encoder:", options)


def _choose_quality(
    vcodec: str, engine: str, media: MediaInfo, hardware: HardwareCapabilities
) -> dict:
    if prompts.ask_confirm(
        "Pick from calculated compression presets (with estimated size)?", default=True
    ):
        rows = [
            r
            for r in preset_calc.estimate_presets(media, hardware)
            if r.codec == vcodec and r.engine == engine
        ]
        if rows:
            chosen = prompts.choose(
                "Quality tier:",
                [
                    (f"{r.tier_name} — ~{r.estimated_size_mb}MB, {r.speed_note}", r)
                    for r in rows
                ],
            )
            return {"quality_mode": "bitrate", "video_kbps": chosen.target_video_kbps}

    if engine == "hardware":
        quality = prompts.ask_text(
            "Quality (1-100, higher = better, larger):", default="65"
        )
        return {"quality_mode": "hw_quality", "hw_quality": int(quality)}

    default_crf = "32" if vcodec in ("av1", "vp9") else "23"
    crf = prompts.ask_text(
        "CRF (lower = higher quality/larger file):", default=default_crf
    )
    return {"quality_mode": "crf", "crf": int(crf)}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    output_args: list[str] = []
    vcodec = params.get("vcodec")

    if vcodec == "copy_v":
        output_args += ["-c:v", "copy"]
    elif vcodec == "prores":
        engine = params.get("engine", "software")
        encoder = (
            _VIDEO_CODECS_PRORES_HW if engine == "hardware" else _VIDEO_CODECS_PRORES_SW
        )
        output_args += ["-c:v", encoder, "-profile:v", params.get("prores_profile", "2")]
    elif vcodec:
        codec_info = _VIDEO_CODECS[vcodec]
        engine = params.get("engine", "software")
        encoder = codec_info["hw"] if engine == "hardware" and codec_info["hw"] else codec_info["sw"]
        output_args += ["-c:v", encoder]
        output_args += _quality_args(vcodec, engine, params)

    acodec = params.get("acodec", "aac")
    audio_info = _AUDIO_CODECS[acodec]
    output_args += ["-c:a", audio_info["encoder"]]
    if audio_info["bitrate_k"]:
        output_args += ["-b:a", f"{audio_info['bitrate_k']}k"]

    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Convert to {params.get('container', 'mp4').upper()}",
        output_args=output_args,
        serializable={"container": params.get("container", "mp4")},
    )


_VIDEO_CODECS_PRORES_SW = "prores_ks"
_VIDEO_CODECS_PRORES_HW = "prores_videotoolbox"


def _quality_args(vcodec: str, engine: str, params: dict) -> list[str]:
    if params.get("quality_mode") == "bitrate":
        return ["-b:v", f"{params['video_kbps']}k"]
    if params.get("quality_mode") == "hw_quality" or engine == "hardware":
        return ["-q:v", str(params.get("hw_quality", 65))]
    crf = str(params.get("crf", 23))
    if vcodec == "vp9":
        return ["-crf", crf, "-b:v", "0"]
    return ["-crf", crf]


def output_extension(params: dict) -> str:
    return params.get("container", "mp4")
