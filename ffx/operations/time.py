from __future__ import annotations

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings, Preset
from ffx.ui import prompts

name = "time"
display_name = "Time"
description = "Frame rate, speed, loops, and freezes"

_COMMON_FPS = [
    ("23.976", "24000/1001"),
    ("24", "24"),
    ("25", "25"),
    ("29.97", "30000/1001"),
    ("30", "30"),
    ("50", "50"),
    ("59.94", "60000/1001"),
    ("60", "60"),
]

PRESETS = [
    Preset("2x speed (silent)", "Double speed, audio dropped", {"mode": "speed", "factor": 2.0, "keep_audio": False}),
    Preset("Slow motion 0.5x", "Half speed, audio pitch-preserved", {"mode": "speed", "factor": 0.5, "keep_audio": True}),
    Preset("Timelapse 20x", "20x speed, silent", {"mode": "speed", "factor": 20.0, "keep_audio": False}),
    Preset("Loop twice", "Play the clip back to back, twice", {"mode": "loop", "count": 2}),
    Preset("Freeze outro (3s)", "Hold the last frame for 3 extra seconds", {"mode": "freeze", "duration": "3"}),
]


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    preset = prompts.choose_preset(PRESETS, message="Time — choose a preset:")
    if preset is not None:
        return dict(preset.values)

    mode = prompts.choose(
        "What kind of time change?",
        [
            ("Convert frame rate", "framerate"),
            ("Change speed", "speed"),
            ("Loop", "loop"),
            ("Freeze the last frame", "freeze"),
        ],
    )

    if mode == "framerate":
        fps = prompts.choose("Target frame rate:", _COMMON_FPS, default="30")
        method = prompts.choose(
            "Method:",
            [
                ("Duplicate/drop frames (fast)", "duplicate"),
                ("Motion-interpolated (smoother, much slower)", "interpolate"),
            ],
            default="duplicate",
        )
        return {"mode": "framerate", "fps": fps, "method": method}

    if mode == "speed":
        factor = float(
            prompts.ask_text("Speed factor (2 = double, 0.5 = half, etc.):", default="2")
        )
        keep_audio = prompts.ask_confirm(
            "Keep audio?", default=True, hint="Pitch-preserved tempo change, not just faster/slower."
        )
        return {"mode": "speed", "factor": factor, "keep_audio": keep_audio}

    if mode == "loop":
        count = int(prompts.ask_text("Play the clip how many times?", default="2"))
        return {"mode": "loop", "count": count}

    duration = prompts.ask_timestamp("Freeze duration (seconds):", default="3")
    return {"mode": "freeze", "duration": duration}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    mode = params["mode"]

    if mode == "framerate":
        return _build_framerate(params)
    if mode == "speed":
        return _build_speed(params)
    if mode == "loop":
        return _build_loop(params)
    if mode == "freeze":
        return _build_freeze(params, media)

    raise ValueError(f"unknown time mode: {mode}")


def _build_framerate(params: dict) -> OperationSettings:
    fps = params["fps"]
    if params.get("method") == "interpolate":
        return OperationSettings(
            name=name,
            display_name=display_name,
            description=f"Conform to {fps}fps (motion-interpolated)",
            video_filter=[f"minterpolate=fps={fps}:mi_mode=mci"],
            serializable={},
        )
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Conform to {fps}fps",
        output_args=["-r", fps],
        serializable={},
    )


def _build_speed(params: dict) -> OperationSettings:
    factor = params["factor"]
    keep_audio = params.get("keep_audio", True)
    video_filter = [f"setpts={1 / factor}*PTS"]
    audio_filter = _atempo_chain(factor) if keep_audio else []
    output_args = [] if keep_audio else ["-an"]

    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"{factor}x speed" + ("" if keep_audio else " (silent)"),
        video_filter=video_filter,
        audio_filter=audio_filter,
        output_args=output_args,
        serializable={},
    )


def _atempo_chain(factor: float) -> list[str]:
    """Decompose an arbitrary speed factor into atempo filters, each of
    which only accepts 0.5-2.0. e.g. 4x -> atempo=2.0,atempo=2.0.
    """
    if factor <= 0:
        raise ValueError("speed factor must be positive")
    stages: list[float] = []
    remaining = factor
    while remaining > 2.0:
        stages.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        stages.append(0.5)
        remaining /= 0.5
    stages.append(round(remaining, 6))
    return [f"atempo={s}" for s in stages]


def _build_loop(params: dict) -> OperationSettings:
    count = max(int(params.get("count", 2)), 1)
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Loop {count}x",
        args_before_input=["-stream_loop", str(count - 1)],
        serializable={},
    )


def _build_freeze(params: dict, media: MediaInfo) -> OperationSettings:
    duration = params.get("duration", "3")
    video_filter = [f"tpad=stop_mode=clone:stop_duration={duration}"]
    audio_filter = [f"apad=pad_dur={duration}"] if media.primary_audio else []

    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Freeze last frame for {duration}s",
        video_filter=video_filter,
        audio_filter=audio_filter,
        serializable={},
    )
