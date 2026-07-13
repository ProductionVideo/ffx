from __future__ import annotations

from pathlib import Path

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings
from ffx.operations._filterescape import quote_filter_value
from ffx.ui import prompts
from ffx.ui.theme import console

name = "caption"
display_name = "Caption"
description = "Burn in or attach a subtitle file (.srt/.vtt/.ass)"

# Which text subtitle codec each container family expects when muxing
# subtitles as a selectable track (rather than burning them in).
_SOFT_CODECS = [
    ("MP4 / MOV (mov_text)", "mov_text"),
    ("MKV (srt)", "srt"),
    ("WebM (webvtt)", "webvtt"),
]


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict | None:
    subs = prompts.ask_existing_path("Path to the subtitle file (.srt, .vtt, .ass):")

    mode = prompts.choose(
        "How should the captions be applied?",
        [
            ("Burn in — drawn onto the pixels, always visible", "burn"),
            ("Soft track — selectable/toggleable in the player", "soft"),
        ],
        default="burn",
    )

    if mode == "burn":
        if not hardware.has_filter("subtitles"):
            console.print(
                "This ffmpeg build can't burn subtitles (the filter needs libass). "
                "`brew install ffmpeg-full` includes it.",
                style="ffx.error",
            )
            return None
        return {"mode": "burn", "path": str(subs)}

    codec = prompts.choose(
        "Subtitle format (match your target container):", _SOFT_CODECS, default="mov_text"
    )
    return {"mode": "soft", "path": str(subs), "codec": codec}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    path = Path(params["path"])

    if params["mode"] == "burn":
        return OperationSettings(
            name=name,
            display_name=display_name,
            description=f"Burn in {path.name}",
            video_filter=[f"subtitles={quote_filter_value(str(path))}"],
            serializable={},
        )

    codec = params.get("codec", "mov_text")
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Attach {path.name} as a subtitle track ({codec})",
        extra_inputs=[path],
        extra_input_args=[[]],
        # Keep every original stream, add the subtitle file's first stream.
        non_video_output_args=["-map", "0", "-map", "{in0}:0", "-c:s", codec],
        serializable={},
    )
