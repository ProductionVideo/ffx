from __future__ import annotations

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings, Preset
from ffx.operations._filterescape import quote_filter_value
from ffx.ui import prompts
from ffx.ui.theme import console

name = "text"
display_name = "Text"
description = "Burn in captions, titles, or a watermark"

PRESETS = [
    Preset(
        "Lower-third caption",
        "White text, bottom-left, with a background box",
        {"position": "bottom-left", "size": 36, "color": "white", "box": True},
    ),
    Preset(
        "Centered title card",
        "Large centered text, no background box",
        {"position": "center", "size": 64, "color": "white", "box": False},
    ),
    Preset(
        "Bottom-right watermark",
        "Small semi-transparent watermark text",
        {"position": "bottom-right", "size": 24, "color": "white@0.6", "box": False},
    ),
]

_POSITION_LABELS = {
    "top-left": "Top-left",
    "top-center": "Top-center",
    "top-right": "Top-right",
    "center": "Center",
    "bottom-left": "Bottom-left",
    "bottom-center": "Bottom-center",
    "bottom-right": "Bottom-right",
}

# 20px margin from each edge; text_w/text_h are drawtext's own measured
# extents of the rendered string, so centering/right/bottom alignment
# stays correct regardless of font size or string length.
_POSITION_EXPR = {
    "top-left": ("20", "20"),
    "top-center": ("(w-text_w)/2", "20"),
    "top-right": ("w-text_w-20", "20"),
    "center": ("(w-text_w)/2", "(h-text_h)/2"),
    "bottom-left": ("20", "h-text_h-20"),
    "bottom-center": ("(w-text_w)/2", "h-text_h-20"),
    "bottom-right": ("w-text_w-20", "h-text_h-20"),
}


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict | None:
    if not hardware.has_filter("drawtext"):
        console.print(
            "This ffmpeg build doesn't have the 'drawtext' filter (it needs libfreetype). "
            "Homebrew's default ffmpeg formula doesn't include it - try "
            "`brew install ffmpeg-full` instead.",
            style="ffx.error",
        )
        return None

    preset = prompts.choose_preset(PRESETS, message="Text — choose a style:")
    if preset is not None:
        params = dict(preset.values)
    else:
        position = prompts.choose(
            "Position:",
            [(label, key) for key, label in _POSITION_LABELS.items()],
            default="bottom-center",
        )
        size = prompts.ask_int("Font size (px):", default=36, min_allowed=8, max_allowed=300)
        color = prompts.ask_text("Text color (name or hex, e.g. white, #ffcc00):", default="white")
        box = prompts.ask_confirm("Add a semi-transparent background box behind the text?", default=True)
        params = {"position": position, "size": size, "color": color, "box": box}

    params["text"] = prompts.ask_text("Text to display:", default="")

    timed = prompts.ask_confirm(
        "Only show the text for part of the video (instead of the whole thing)?", default=False
    )
    if timed:
        params["start"] = prompts.ask_float("Start time (seconds):", default=0.0, min_allowed=0)
        params["end"] = prompts.ask_float("End time (seconds):", default=media.duration or 0.0, min_allowed=0)

    return params


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    position = params.get("position", "bottom-center")
    x_expr, y_expr = _POSITION_EXPR[position]
    text = params.get("text", "")

    parts = [
        f"drawtext=text={quote_filter_value(text)}",
        f"fontsize={params.get('size', 36)}",
        f"fontcolor={params.get('color', 'white')}",
        f"x={x_expr}",
        f"y={y_expr}",
    ]
    if params.get("box"):
        parts += ["box=1", "boxcolor=black@0.5", "boxborderw=10"]
    if "start" in params and "end" in params:
        parts.append(f"enable='between(t,{params['start']},{params['end']})'")

    desc = f"Draw text {text!r} ({_POSITION_LABELS[position]})"
    if "start" in params and "end" in params:
        desc += f" from {params['start']}s to {params['end']}s"

    return OperationSettings(
        name=name,
        display_name=display_name,
        description=desc,
        video_filter=[":".join(parts)],
        serializable={},
    )
