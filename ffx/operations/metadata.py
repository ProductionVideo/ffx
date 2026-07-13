from __future__ import annotations

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings
from ffx.ui import prompts

name = "metadata"
display_name = "Metadata"
description = "Add, change, or strip file tags"

_FIELDS = [
    ("title", "Title"),
    ("artist", "Artist"),
    ("copyright", "Copyright"),
    ("comment", "Comment"),
    ("date", "Creation date"),
    ("language", "Language (e.g. eng, fra)"),
]


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    mode = prompts.choose(
        "What do you want to do with metadata?",
        [
            ("Edit tags (title, artist, etc.)", "edit"),
            ("Strip all metadata", "strip"),
        ],
    )
    if mode == "strip":
        return {"mode": "strip"}

    values = {}
    for key, label in _FIELDS:
        value = prompts.ask_text(f"{label} (blank = leave unchanged):")
        if value:
            values[key] = value
    return {"mode": "edit", "values": values}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    if params["mode"] == "strip":
        return OperationSettings(
            name=name,
            display_name=display_name,
            description="Strip all metadata",
            non_video_output_args=["-map_metadata", "-1"],
            serializable={},
        )

    values = params.get("values", {})
    non_video_output_args = []
    language = values.get("language")
    for key, value in values.items():
        if key == "language":
            continue
        non_video_output_args += ["-metadata", f"{key}={value}"]
    if language:
        if media.primary_video:
            non_video_output_args += ["-metadata:s:v:0", f"language={language}"]
        if media.primary_audio:
            non_video_output_args += ["-metadata:s:a:0", f"language={language}"]

    fields_set = list(values.keys()) + (["language"] if language else [])
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Set {', '.join(fields_set)}" if fields_set else "No metadata changes",
        non_video_output_args=non_video_output_args,
        serializable={},
    )
