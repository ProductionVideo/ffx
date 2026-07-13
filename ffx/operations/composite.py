from __future__ import annotations

from pathlib import Path

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings
from ffx.ui import prompts

name = "composite"
display_name = "Composite"
description = "Overlay, picture-in-picture, stack, or chroma key with a second file"

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}

_POSITION_LABELS = {
    "top-left": "Top-left",
    "top-center": "Top-center",
    "top-right": "Top-right",
    "center": "Center",
    "bottom-left": "Bottom-left",
    "bottom-center": "Bottom-center",
    "bottom-right": "Bottom-right",
}

# overlay's own coordinate variables (main_w/main_h/overlay_w/overlay_h) -
# distinct from drawtext's w/text_w in text.py, since these two filters
# expose different expression variable names for the same idea.
_POSITION_EXPR = {
    "top-left": ("20", "20"),
    "top-center": ("(main_w-overlay_w)/2", "20"),
    "top-right": ("main_w-overlay_w-20", "20"),
    "center": ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
    "bottom-left": ("20", "main_h-overlay_h-20"),
    "bottom-center": ("(main_w-overlay_w)/2", "main_h-overlay_h-20"),
    "bottom-right": ("main_w-overlay_w-20", "main_h-overlay_h-20"),
}


def _is_image(path: str) -> bool:
    return Path(path).suffix.lower() in _IMAGE_EXTS


def _loop_args(path: str) -> list[str]:
    # A still image has no inherent duration - loop it indefinitely and
    # let the overlay/hstack/vstack filter's shortest=1 (or the main
    # video's own length) decide where the output actually ends.
    return ["-loop", "1"] if _is_image(path) else []


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    mode = prompts.choose(
        "What kind of composite?",
        [
            ("Overlay / watermark (image or video)", "watermark"),
            ("Picture-in-picture", "pip"),
            ("Side-by-side / stacked", "stack"),
            ("Chroma key (green screen)", "chromakey"),
        ],
    )

    if mode == "watermark":
        path = prompts.ask_existing_path("Path to the watermark/overlay image or video:")
        position = prompts.choose(
            "Position:", [(label, key) for key, label in _POSITION_LABELS.items()], default="bottom-right"
        )
        opacity = prompts.ask_float("Opacity (0-1):", default=0.8, min_allowed=0.05, max_allowed=1.0)
        return {"mode": "watermark", "overlay_path": str(path), "position": position, "opacity": opacity}

    if mode == "pip":
        path = prompts.ask_existing_path("Path to the picture-in-picture video:")
        position = prompts.choose(
            "Position:",
            [(label, key) for key, label in _POSITION_LABELS.items() if key != "center"],
            default="bottom-right",
        )
        scale_percent = prompts.ask_int("Size as % of the main video:", default=25, min_allowed=5, max_allowed=90)
        return {"mode": "pip", "overlay_path": str(path), "position": position, "scale_percent": scale_percent}

    if mode == "stack":
        path = prompts.ask_existing_path("Path to the second video or image:")
        direction = prompts.choose(
            "Arrange:", [("Side by side (horizontal)", "horizontal"), ("Stacked (vertical)", "vertical")]
        )
        return {"mode": "stack", "second_path": str(path), "direction": direction}

    path = prompts.ask_existing_path("Path to the background image or video:")
    color = prompts.ask_text("Key color to remove (name or hex, e.g. green, 0x00FF00):", default="green")
    similarity = prompts.ask_float(
        "Similarity (0-1, higher removes more of the key color):", default=0.3, min_allowed=0.01, max_allowed=1.0
    )
    blend = prompts.ask_float("Edge blend (0-1):", default=0.1, min_allowed=0.0, max_allowed=1.0)
    return {
        "mode": "chromakey",
        "background_path": str(path),
        "color": color,
        "similarity": similarity,
        "blend": blend,
    }


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    mode = params["mode"]
    if mode == "watermark":
        return _build_watermark(params)
    if mode == "pip":
        return _build_pip(params)
    if mode == "stack":
        return _build_stack(params)
    if mode == "chromakey":
        return _build_chromakey(params)
    raise ValueError(f"unknown composite mode: {mode}")


def _build_watermark(params: dict) -> OperationSettings:
    path = params["overlay_path"]
    x, y = _POSITION_EXPR[params["position"]]
    opacity = params["opacity"]
    fc = f"[{{in0}}]format=rgba,colorchannelmixer=aa={opacity}[wm];[0:v][wm]overlay={x}:{y}:shortest=1[outv]"
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Overlay watermark ({Path(path).name}, {_POSITION_LABELS[params['position']]}, {opacity:.0%} opacity)",
        extra_inputs=[Path(path)],
        extra_input_args=[_loop_args(path)],
        filter_complex=fc,
        output_args=["-map", "[outv]", "-map", "0:a?"],
        serializable={},
    )


def _build_pip(params: dict) -> OperationSettings:
    path = params["overlay_path"]
    x, y = _POSITION_EXPR[params["position"]]
    fraction = params["scale_percent"] / 100
    fc = f"[{{in0}}]scale=iw*{fraction}:ih*{fraction}[pip];[0:v][pip]overlay={x}:{y}:shortest=1[outv]"
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=(
            f"Picture-in-picture ({Path(path).name}, {params['scale_percent']}% size, "
            f"{_POSITION_LABELS[params['position']]})"
        ),
        extra_inputs=[Path(path)],
        extra_input_args=[_loop_args(path)],
        filter_complex=fc,
        output_args=["-map", "[outv]", "-map", "0:a?"],
        serializable={},
    )


def _build_stack(params: dict) -> OperationSettings:
    path = params["second_path"]
    direction = params["direction"]
    # scale=w:h with a second (reference) input link is the modern
    # replacement for the now-deprecated scale2ref: "rw"/"rh" resolve to
    # the reference's (the main video's) width/height, so the second
    # file is resized to match without needing a separate passthrough pad.
    if direction == "horizontal":
        fc = "[{in0}][0:v]scale=w=-2:h=rh[ov];[0:v][ov]hstack=inputs=2[outv]"
        label = "side by side"
    else:
        fc = "[{in0}][0:v]scale=w=rw:h=-2[ov];[0:v][ov]vstack=inputs=2[outv]"
        label = "stacked vertically"
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Stack with {Path(path).name} ({label})",
        extra_inputs=[Path(path)],
        extra_input_args=[_loop_args(path)],
        filter_complex=fc,
        output_args=["-map", "[outv]", "-map", "0:a?"],
        serializable={},
    )


def _build_chromakey(params: dict) -> OperationSettings:
    path = params["background_path"]
    color, similarity, blend = params["color"], params["similarity"], params["blend"]
    fc = (
        "[{in0}][0:v]scale=w=rw:h=rh[bg];"
        f"[0:v]chromakey={color}:{similarity}:{blend}[fg];"
        "[bg][fg]overlay=shortest=1[outv]"
    )
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Chroma key over {Path(path).name} (key {color})",
        extra_inputs=[Path(path)],
        extra_input_args=[_loop_args(path)],
        filter_complex=fc,
        output_args=["-map", "[outv]", "-map", "0:a?"],
        serializable={},
    )
