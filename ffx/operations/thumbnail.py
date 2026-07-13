from __future__ import annotations

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings
from ffx.ui import prompts

name = "thumbnail"
display_name = "Thumbnail"
description = "Grab a frame as an image, or a contact-sheet grid"


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    mode = prompts.choose(
        "What kind of thumbnail?",
        [
            ("Single frame at a timestamp", "frame"),
            ("Contact sheet — an evenly sampled grid of the whole video", "sheet"),
        ],
    )

    if mode == "frame":
        timestamp = prompts.ask_timestamp("Grab the frame at:", default="0")
        fmt = _ask_format()
        return {"mode": "frame", "timestamp": timestamp, "format": fmt}

    columns = prompts.ask_int("Columns:", default=4, min_allowed=1, max_allowed=12)
    rows = prompts.ask_int("Rows:", default=4, min_allowed=1, max_allowed=12)
    tile_width = prompts.ask_int(
        "Width of each tile (px):", default=320, min_allowed=64, max_allowed=1920
    )
    fmt = _ask_format()
    return {"mode": "sheet", "columns": columns, "rows": rows, "tile_width": tile_width, "format": fmt}


def _ask_format() -> str:
    return prompts.choose("Image format:", [("PNG", "png"), ("JPEG", "jpg")], default="png")


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    if params["mode"] == "frame":
        timestamp = params.get("timestamp", "0")
        return OperationSettings(
            name=name,
            display_name=display_name,
            description=f"Frame at {timestamp} → {params.get('format', 'png').upper()}",
            # -ss before -i: keyframe-fast seek; exactness doesn't matter
            # more than speed when grabbing one representative frame.
            args_before_input=["-ss", timestamp],
            output_args=["-frames:v", "1"],
            serializable={},
        )

    columns = params.get("columns", 4)
    rows = params.get("rows", 4)
    tiles = columns * rows
    duration = media.duration or 0.0
    # One frame per grid cell, spread evenly across the whole runtime.
    sample_fps = tiles / duration if duration > 0 else 1
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Contact sheet {columns}x{rows} → {params.get('format', 'png').upper()}",
        video_filter=[
            f"fps={sample_fps:.6f}",
            f"scale={params.get('tile_width', 320)}:-1",
            f"tile={columns}x{rows}",
        ],
        output_args=["-frames:v", "1"],
        serializable={},
    )


def output_extension(params: dict) -> str:
    return params.get("format", "png")
