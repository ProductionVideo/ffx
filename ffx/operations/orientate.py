from __future__ import annotations

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings, Preset
from ffx.ui import prompts

name = "orientate"
display_name = "Orientate"
description = "Rotate or flip the frame"

PRESETS = [
    Preset("Rotate 90° clockwise", "For footage shot sideways", {"mode": "rotate", "angle": 90}),
    Preset("Rotate 90° counter-clockwise", "For footage shot sideways the other way", {"mode": "rotate", "angle": -90}),
    Preset("Rotate 180°", "Flip upside-down footage the right way up", {"mode": "rotate", "angle": 180}),
    Preset("Flip horizontal", "Mirror left/right", {"mode": "flip", "axis": "horizontal"}),
    Preset("Flip vertical", "Mirror top/bottom", {"mode": "flip", "axis": "vertical"}),
]


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    preset = prompts.choose_preset(PRESETS, message="Orientate — choose a preset:")
    if preset is not None:
        return dict(preset.values)

    mode = prompts.choose("Rotate or flip?", [("Rotate", "rotate"), ("Flip", "flip")])
    if mode == "rotate":
        angle = prompts.choose(
            "Rotate by:",
            [("90° clockwise", 90), ("90° counter-clockwise", -90), ("180°", 180)],
        )
        return {"mode": "rotate", "angle": angle}

    axis = prompts.choose("Flip which way?", [("Horizontal (mirror left/right)", "horizontal"), ("Vertical (mirror top/bottom)", "vertical")])
    return {"mode": "flip", "axis": axis}


_ROTATE_FILTERS = {
    90: "transpose=1",
    -90: "transpose=2",
    180: "transpose=1,transpose=1",
}

_FLIP_FILTERS = {
    "horizontal": "hflip",
    "vertical": "vflip",
}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    mode = params["mode"]
    if mode == "rotate":
        angle = params["angle"]
        vf = _ROTATE_FILTERS[angle]
        desc = f"Rotate {angle}°"
    else:
        axis = params["axis"]
        vf = _FLIP_FILTERS[axis]
        desc = f"Flip {axis}"

    return OperationSettings(
        name=name,
        display_name=display_name,
        description=desc,
        video_filter=[vf],
        serializable={},
    )
