from __future__ import annotations

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings, Preset
from ffx.ui import prompts

name = "scale"
display_name = "Scale"
description = "Resize to fit, fill, or an exact size"

_ALGO_LABELS = {
    "bilinear": "Fast (bilinear)",
    "bicubic": "Balanced (bicubic)",
    "lanczos": "High quality (lanczos)",
}

PRESETS = [
    Preset(
        "1080p (Full HD)",
        "Fit inside 1920x1080, keep aspect ratio",
        {"mode": "fit", "width": 1920, "height": 1080, "algo": "lanczos"},
    ),
    Preset(
        "4K / UHD",
        "Fit inside 3840x2160, keep aspect ratio",
        {"mode": "fit", "width": 3840, "height": 2160, "algo": "lanczos"},
    ),
    Preset(
        "720p (HD)",
        "Fit inside 1280x720, keep aspect ratio",
        {"mode": "fit", "width": 1280, "height": 720, "algo": "lanczos"},
    ),
    Preset(
        "Square for social (1080x1080)",
        "Scale and crop to fill a 1:1 square",
        {"mode": "fill", "width": 1080, "height": 1080, "algo": "lanczos"},
    ),
    Preset(
        "Vertical for stories (1080x1920)",
        "Scale and crop to fill a 9:16 vertical frame",
        {"mode": "fill", "width": 1080, "height": 1920, "algo": "lanczos"},
    ),
    Preset(
        "Half size",
        "Scale to 50% of the source resolution",
        {"mode": "percent", "percent": 50, "algo": "bilinear"},
    ),
]


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    preset = prompts.choose_preset(PRESETS, message="Scale — choose a preset:")
    if preset is not None:
        return dict(preset.values)

    mode = prompts.fuzzy(
        "How do you want to scale?",
        [
            ("By width", "width"),
            ("By height", "height"),
            ("Fit (letterbox)", "fit"),
            ("Fill (crop excess)", "fill"),
            ("Stretch (ignores aspect ratio)", "stretch"),
            ("By percentage", "percent"),
        ],
        hint="Width/height/fit/fill keep aspect ratio; stretch doesn't.",
    )

    params: dict = {"mode": mode}
    if mode == "width":
        params["width"] = prompts.ask_int("Target width (px):", default=1280, min_allowed=2)
    elif mode == "height":
        params["height"] = prompts.ask_int("Target height (px):", default=720, min_allowed=2)
    elif mode == "percent":
        params["percent"] = prompts.ask_int("Percent of source size:", default=50, min_allowed=1)
    else:
        params["width"] = prompts.ask_int("Target width (px):", default=1920, min_allowed=2)
        params["height"] = prompts.ask_int("Target height (px):", default=1080, min_allowed=2)

    params["algo"] = prompts.choose(
        "Scaling algorithm:", [(label, key) for key, label in _ALGO_LABELS.items()]
    )
    return params


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    mode = params["mode"]
    algo = params.get("algo", "lanczos")

    if mode == "width":
        vf = f"scale={params['width']}:-2:flags={algo}"
    elif mode == "height":
        vf = f"scale=-2:{params['height']}:flags={algo}"
    elif mode == "fit":
        w, h = params["width"], params["height"]
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags={algo},"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        )
    elif mode == "fill":
        w, h = params["width"], params["height"]
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase:flags={algo},crop={w}:{h}"
    elif mode == "stretch":
        w, h = params["width"], params["height"]
        vf = f"scale={w}:{h}:flags={algo}"
    elif mode == "percent":
        fraction = params["percent"] / 100
        # trunc(...)/2*2 keeps both dimensions even, which most codecs
        # require for 4:2:0 chroma subsampling.
        vf = f"scale=trunc(iw*{fraction}/2)*2:trunc(ih*{fraction}/2)*2:flags={algo}"
    else:
        raise ValueError(f"unknown scale mode: {mode}")

    return OperationSettings(
        name=name,
        display_name=display_name,
        description=_describe(mode, params),
        video_filter=[vf],
        serializable={},
    )


def _describe(mode: str, params: dict) -> str:
    if mode == "percent":
        return f"Scale to {params['percent']}% of source size"
    if mode in ("width", "height"):
        return f"Scale by {mode} to {params.get(mode)}px"
    return f"Scale ({mode}) to {params['width']}x{params['height']}"
