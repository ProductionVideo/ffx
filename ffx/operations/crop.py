from __future__ import annotations

import re
import subprocess

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings, Preset
from ffx.ui import prompts
from ffx.ui.theme import console

name = "crop"
display_name = "Crop"
description = "Reframe to a ratio or exact rectangle"

_CROPDETECT_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")

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
            ("Auto-detect crop region (analyzes the video)", "auto"),
            ("Add a border", "border"),
        ],
    )
    if mode == "aspect":
        aspect = prompts.ask_text("Target aspect ratio (e.g. 16:9, 1:1, 9:16):", default="16:9")
        return {"mode": "aspect", "aspect": aspect}

    if mode == "auto":
        detected = _detect_crop(media)
        if detected is None:
            console.print(
                "Couldn't detect a crop region (no letterboxing found) - falling back to manual entry.",
                style="ffx.warn",
            )
            mode = "rect"
        else:
            w, h, x, y = detected
            console.print(f"Detected crop: {w}x{h} at ({x},{y})", style="ffx.ok")
            return {"mode": "rect", "width": w, "height": h, "x": x, "y": y}

    if mode == "border":
        thickness = int(prompts.ask_text("Border thickness (px):", default="20"))
        color = prompts.ask_text("Border color (name or hex, e.g. black, white, #ff0000):", default="black")
        return {"mode": "border", "thickness": thickness, "color": color}

    return {
        "mode": "rect",
        "width": int(prompts.ask_text("Crop width (px):", default="1280")),
        "height": int(prompts.ask_text("Crop height (px):", default="720")),
        "x": int(prompts.ask_text("Crop X offset (px from left, 0 = centered by ffmpeg):", default="0")),
        "y": int(prompts.ask_text("Crop Y offset (px from top, 0 = centered by ffmpeg):", default="0")),
    }


def _detect_crop(media: MediaInfo) -> tuple[int, int, int, int] | None:
    sample_duration = min(media.duration, 20) if media.duration else 20
    args = [
        "ffmpeg", "-i", str(media.path),
        "-t", str(sample_duration),
        "-vf", "cropdetect=24:2:0",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None
    matches = _CROPDETECT_RE.findall(result.stderr)
    if not matches:
        return None
    w, h, x, y = matches[-1]
    return int(w), int(h), int(x), int(y)


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    mode = params["mode"]
    if mode == "aspect":
        vf = _aspect_crop_filter(params["aspect"])
        desc = f"Crop to {params['aspect']} (centered)"
    elif mode == "border":
        t = params["thickness"]
        color = params.get("color", "black")
        vf = f"pad=iw+{2 * t}:ih+{2 * t}:{t}:{t}:color={color}"
        desc = f"Add {t}px {color} border"
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
