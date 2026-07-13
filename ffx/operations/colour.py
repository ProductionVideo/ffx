from __future__ import annotations

from pathlib import Path

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings, Preset
from ffx.operations._filterescape import quote_filter_value
from ffx.ui import prompts

name = "colour"
display_name = "Colour"
description = "Grade, tint, or apply a LUT"

PRESETS = [
    Preset("Black & white", "Remove all colour", {"mode": "bw"}),
    Preset(
        "Boost saturation",
        "Make colours pop (+40% saturation)",
        {"mode": "adjust", "brightness": 0.0, "contrast": 1.0, "saturation": 1.4, "gamma": 1.0},
    ),
    Preset("Warmer", "Shift white balance toward orange", {"mode": "temperature", "kelvin": 4500}),
    Preset("Cooler", "Shift white balance toward blue", {"mode": "temperature", "kelvin": 8500}),
    Preset("Faded / vintage", "Lower contrast and saturation with a soft vignette", {"mode": "vintage"}),
]


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    preset = prompts.choose_preset(PRESETS, message="Colour — choose a preset:")
    if preset is not None:
        return dict(preset.values)

    mode = prompts.choose(
        "How do you want to grade the colour?",
        [
            ("Black & white", "bw"),
            ("Adjust brightness/contrast/saturation/gamma", "adjust"),
            ("Warm/cool white balance", "temperature"),
            ("Faded / vintage look", "vintage"),
            ("Apply a LUT file (.cube)", "lut"),
        ],
    )

    if mode == "bw":
        return {"mode": "bw"}

    if mode == "adjust":
        return {
            "mode": "adjust",
            "brightness": prompts.ask_float("Brightness (-1 to 1, 0 = unchanged):", default=0.0, min_allowed=-1, max_allowed=1),
            "contrast": prompts.ask_float("Contrast (0 to 2, 1 = unchanged):", default=1.0, min_allowed=0, max_allowed=2),
            "saturation": prompts.ask_float("Saturation (0 to 3, 1 = unchanged):", default=1.0, min_allowed=0, max_allowed=3),
            "gamma": prompts.ask_float("Gamma (0.1 to 3, 1 = unchanged):", default=1.0, min_allowed=0.1, max_allowed=3),
        }

    if mode == "temperature":
        kelvin = prompts.ask_int(
            "Colour temperature (Kelvin):",
            default=6500,
            min_allowed=2000,
            max_allowed=12000,
            hint="Lower = warmer/orange, higher = cooler/blue.",
        )
        return {"mode": "temperature", "kelvin": kelvin}

    if mode == "vintage":
        return {"mode": "vintage"}

    path = prompts.ask_existing_path("Path to a .cube LUT file:")
    return {"mode": "lut", "path": str(path)}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    mode = params["mode"]

    if mode == "bw":
        vf, desc = "hue=s=0", "Black & white"
    elif mode == "adjust":
        b, c, s, g = params["brightness"], params["contrast"], params["saturation"], params["gamma"]
        vf = f"eq=brightness={b}:contrast={c}:saturation={s}:gamma={g}"
        desc = f"Adjust colour (brightness {b:+.2f}, contrast {c:.2f}, saturation {s:.2f}, gamma {g:.2f})"
    elif mode == "temperature":
        kelvin = params["kelvin"]
        vf = f"colortemperature=temperature={kelvin}"
        desc = f"White balance to {kelvin}K"
    elif mode == "vintage":
        vf = "eq=contrast=0.85:saturation=0.7:brightness=0.02,colorbalance=rs=0.12:gs=0.04:bs=-0.12,vignette"
        desc = "Faded / vintage look"
    elif mode == "lut":
        path = params["path"]
        vf = f"lut3d=file={quote_filter_value(path)}"
        desc = f"Apply LUT: {Path(path).name}"
    else:
        raise ValueError(f"unknown colour mode: {mode}")

    return OperationSettings(
        name=name,
        display_name=display_name,
        description=desc,
        video_filter=[vf],
        serializable={},
    )
