from __future__ import annotations

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings, Preset
from ffx.ui import prompts

name = "crop"
display_name = "Crop"
description = "Reframe to a ratio or exact rectangle"

PRESETS = [
    Preset(
        "Landscape 16:9",
        "Crop the center to a widescreen frame",
        {"mode": "aspect", "aspect": "16:9"},
    ),
    Preset(
        "Vertical / social 9:16",
        "Crop the center for Stories/Reels/Shorts",
        {"mode": "aspect", "aspect": "9:16"},
    ),
    Preset(
        "Square 1:1",
        "Crop the center to a square",
        {"mode": "aspect", "aspect": "1:1"},
    ),
    Preset(
        "Portrait 4:5",
        "Crop the center for Instagram portrait posts",
        {"mode": "aspect", "aspect": "4:5"},
    ),
]


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    preset = prompts.choose_preset(PRESETS, message="Crop — choose a preset:")
    if preset is not None:
        return dict(preset.values)

    mode = prompts.choose(
        "How do you want to crop?",
        [
            ("By aspect ratio (centered)", "aspect"),
            ("Exact rectangle", "rect"),
        ],
    )
    if mode == "aspect":
        aspect = prompts.ask_text("Target aspect ratio (e.g. 16:9, 1:1, 9:16):", default="16:9")
        return {"mode": "aspect", "aspect": aspect}

    return {
        "mode": "rect",
        "width": int(prompts.ask_text("Crop width (px):", default="1280")),
        "height": int(prompts.ask_text("Crop height (px):", default="720")),
        "x": int(prompts.ask_text("Crop X offset (px from left, 0 = centered by ffmpeg):", default="0")),
        "y": int(prompts.ask_text("Crop Y offset (px from top, 0 = centered by ffmpeg):", default="0")),
    }


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    if params["mode"] == "aspect":
        vf = _aspect_crop_filter(params["aspect"])
        desc = f"Crop to {params['aspect']} (centered)"
    else:
        w, h, x, y = params["width"], params["height"], params["x"], params["y"]
        vf = f"crop={w}:{h}:{x}:{y}"
        desc = f"Crop to {w}x{h} at ({x},{y})"

    return OperationSettings(
        name=name,
        display_name=display_name,
        description=desc,
        video_filter=[vf],
        serializable={},
    )


def _aspect_crop_filter(aspect: str) -> str:
    num, _, den = aspect.partition(":")
    n, d = int(num), int(den)
    # Crop the largest centered rectangle matching the target ratio: if
    # the source is wider than the target, keep full height and crop
    # width (and vice versa). trunc(.../2)*2 keeps both dims even for
    # 4:2:0 chroma subsampling. crop's x/y default to centered already.
    width_expr = f"if(gt(iw/ih,{n}/{d}),trunc(ih*{n}/{d}/2)*2,iw)"
    height_expr = f"if(gt(iw/ih,{n}/{d}),ih,trunc(iw*{d}/{n}/2)*2)"
    return f"crop=w='{width_expr}':h='{height_expr}'"
