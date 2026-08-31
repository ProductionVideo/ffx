from __future__ import annotations

import re

from ffx import probe
from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings, Preset
from ffx.runner import FFmpegCancelled, run_with_output
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
        aspect = prompts.ask_text(
            "Target aspect ratio (e.g. 16:9, 1:1, 9:16):",
            default="16:9",
            validator=prompts.RatioValidator(),
        )
        return {"mode": "aspect", "aspect": aspect}

    if mode == "auto":
        # cropdetect always scans the source *file* directly - if an
        # earlier-queued Scale/Crop/Orientate has already changed the
        # effective frame size (reflected in `media` here), the region
        # it finds is in the wrong coordinate space by the time this
        # crop's filter actually runs.
        raw_video = probe.probe(media.path).primary_video
        video = media.primary_video
        if raw_video and video and (raw_video.width, raw_video.height) != (video.width, video.height):
            console.print(
                f"Heads up: auto-detect scans the original file ({raw_video.width}x{raw_video.height}), "
                f"but the frame will already be {video.width}x{video.height} by the time this crop runs - "
                "the detected region likely won't line up. Exact rectangle (against the frame at this "
                "point) is safer here.",
                style="ffx.warn",
            )
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
        thickness = prompts.ask_int("Border thickness (px):", default=20, min_allowed=1)
        color = prompts.ask_text("Border color (name or hex, e.g. black, white, #ff0000):", default="black")
        return {"mode": "border", "thickness": thickness, "color": color}

    return _ask_rect(media)


def _ask_rect(media: MediaInfo) -> dict:
    # Bounded against the frame as it'll actually be at this point in the
    # pipeline (media is the *effective* MediaInfo by the time this is
    # called - see ffx.dimensions) rather than accepted with no
    # validation at all, which is how a rectangle that no longer fits
    # (typically: cropping after an earlier Scale) used to only surface
    # as ffmpeg's own "Failed to configure input pad" at run time.
    video = media.primary_video
    frame_w = video.width if video and video.width else None
    frame_h = video.height if video and video.height else None

    width = prompts.ask_int(
        "Crop width (px):",
        default=min(1280, frame_w) if frame_w else 1280,
        min_allowed=2,
        max_allowed=frame_w,
        hint=f"Frame is {frame_w}x{frame_h} at this point in the pipeline." if frame_w else "",
    )
    height = prompts.ask_int(
        "Crop height (px):",
        default=min(720, frame_h) if frame_h else 720,
        min_allowed=2,
        max_allowed=frame_h,
    )
    x = prompts.ask_int(
        "Crop X offset (px from left, 0 = centered by ffmpeg):",
        default=0,
        min_allowed=0,
        max_allowed=(frame_w - width) if frame_w else None,
    )
    y = prompts.ask_int(
        "Crop Y offset (px from top, 0 = centered by ffmpeg):",
        default=0,
        min_allowed=0,
        max_allowed=(frame_h - height) if frame_h else None,
    )
    return {"mode": "rect", "width": width, "height": height, "x": x, "y": y}


def _detect_crop(media: MediaInfo) -> tuple[int, int, int, int] | None:
    sample_duration = min(media.duration, 20) if media.duration else 20
    args = [
        "ffmpeg", "-i", str(media.path),
        "-t", str(sample_duration),
        "-vf", "cropdetect=24:2:0",
        "-f", "null", "-",
    ]
    try:
        stderr = run_with_output(
            args, total_duration=sample_duration, console=console, description="Detecting crop region"
        )
    except FFmpegCancelled:
        # Keep Ctrl+C meaning "bail out of the whole app" everywhere else
        # in ffx, rather than introducing a second, different cancel
        # behavior just for this scan.
        raise KeyboardInterrupt from None
    matches = _CROPDETECT_RE.findall(stderr)
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
