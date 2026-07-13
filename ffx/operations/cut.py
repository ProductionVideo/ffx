from __future__ import annotations

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings
from ffx.ui import prompts

name = "cut"
display_name = "Cut"
description = "Trim, slice, or extract a clip"

_MODE_LABELS = {
    "from_start": "Trim from a point to the end",
    "duration": "Extract a fixed duration",
    "between": "Cut between two timestamps",
}


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    mode = prompts.choose("What kind of cut?", [(label, key) for key, label in _MODE_LABELS.items()])
    reencode = not prompts.ask_confirm(
        "Fast cut?",
        default=False,
        hint="Fast snaps to the nearest keyframe (instant, no re-encode). No = frame-accurate.",
    )
    params = {"mode": mode, "reencode": reencode}

    params["start"] = prompts.ask_timestamp(
        "Start timestamp (seconds or HH:MM:SS):", default="0"
    )
    if params["mode"] == "duration":
        params["duration"] = prompts.ask_timestamp("Duration (seconds or HH:MM:SS):", default="10")
    elif params["mode"] == "between":
        params["end"] = prompts.ask_timestamp("End timestamp (seconds or HH:MM:SS):", default="10")

    return params


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    mode = params["mode"]
    reencode = params.get("reencode", True)
    start = params.get("start", "0")

    trim_args: list[str] = ["-ss", start]
    if mode == "duration":
        trim_args += ["-t", params.get("duration", "10")]
    elif mode == "between":
        trim_args += ["-to", params.get("end", "10")]

    if reencode:
        # Output-side seeking: ffmpeg decodes from the start but only
        # writes from `start` onward, giving a frame-accurate cut point.
        return OperationSettings(
            name=name,
            display_name=display_name,
            description=_describe(mode, params),
            output_args=trim_args,
            serializable={},
        )

    # Input-side seeking: fast, but snaps to the nearest keyframe.
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=_describe(mode, params),
        args_before_input=trim_args,
        output_args=["-c", "copy"],
        serializable={},
    )


def _describe(mode: str, params: dict) -> str:
    if mode == "duration":
        return f"Cut {params.get('duration')} starting at {params.get('start')}"
    if mode == "between":
        return f"Cut from {params.get('start')} to {params.get('end')}"
    return f"Trim from {params.get('start')} to the end"
