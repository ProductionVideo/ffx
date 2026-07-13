from __future__ import annotations

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings, Preset
from ffx.ui import prompts

name = "repair"
display_name = "Repair"
description = "Fix timestamps, conform frame rate, faststart, tolerant remux"

PRESETS = [
    Preset(
        "Web-ready (faststart)",
        "Move metadata to the front for instant playback/streaming",
        {"mode": "faststart"},
    ),
    Preset(
        "Fix a broken file",
        "Tolerant remux: ignores decode errors, regenerates timestamps, keeps streams as-is",
        {"mode": "remux"},
    ),
    Preset(
        "Conform to constant frame rate",
        "Fixes variable-frame-rate footage that plays back oddly or drifts out of sync",
        {"mode": "vfr_to_cfr", "fps": None},
    ),
]


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    preset = prompts.choose_preset(PRESETS, message="Repair — choose a preset:")
    if preset is not None:
        return dict(preset.values)

    mode = prompts.choose(
        "What needs fixing?",
        [
            ("Faststart (move metadata to the front)", "faststart"),
            ("Regenerate missing/broken timestamps", "genpts"),
            ("Convert variable frame rate to constant", "vfr_to_cfr"),
            ("Tolerant remux (fix a broken container)", "remux"),
            ("Ignore decode errors while re-encoding", "ignore_errors"),
        ],
    )

    if mode == "vfr_to_cfr":
        video = media.primary_video
        default_fps = str(video.frame_rate) if video and video.frame_rate else "30"
        fps = prompts.ask_text(
            "Target constant frame rate:",
            default=default_fps,
            hint="Defaults to the source's average frame rate.",
        )
        return {"mode": "vfr_to_cfr", "fps": fps}

    return {"mode": mode}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    mode = params["mode"]

    if mode == "faststart":
        return OperationSettings(
            name=name, display_name=display_name, description="Faststart for web playback",
            non_video_output_args=["-movflags", "+faststart"], serializable={},
        )

    if mode == "genpts":
        return OperationSettings(
            name=name, display_name=display_name, description="Regenerate timestamps",
            args_before_input=["-fflags", "+genpts"], serializable={},
        )

    if mode == "vfr_to_cfr":
        fps = params.get("fps") or (
            str(media.primary_video.frame_rate) if media.primary_video and media.primary_video.frame_rate else "30"
        )
        return OperationSettings(
            name=name, display_name=display_name, description=f"Conform to {fps}fps constant frame rate",
            output_args=["-fps_mode", "cfr", "-r", fps], serializable={},
        )

    if mode == "remux":
        return OperationSettings(
            name=name,
            display_name=display_name,
            description="Tolerant remux (fix broken container)",
            args_before_input=["-err_detect", "ignore_err", "-fflags", "+genpts+igndts+discardcorrupt"],
            output_args=["-c", "copy"],
            serializable={},
        )

    if mode == "ignore_errors":
        return OperationSettings(
            name=name,
            display_name=display_name,
            description="Ignore decode errors",
            args_before_input=["-err_detect", "ignore_err", "-fflags", "+discardcorrupt"],
            serializable={},
        )

    raise ValueError(f"unknown repair mode: {mode}")
