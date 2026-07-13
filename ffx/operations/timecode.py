from __future__ import annotations

import re

from InquirerPy.validator import ValidationError, Validator

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings
from ffx.ui import prompts
from ffx.ui.theme import console

name = "timecode"
display_name = "Timecode"
description = "Set the start timecode, or burn a running TC window"

_TC_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[:;]\d{2}$")


class TimecodeValidator(Validator):
    def validate(self, document) -> None:
        if not _TC_RE.match(document.text.strip()):
            raise ValidationError(
                message="Enter HH:MM:SS:FF (use ; before frames for drop-frame)",
                cursor_position=len(document.text),
            )


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict | None:
    mode = prompts.choose(
        "What do you want to do?",
        [
            ("Set the start timecode (metadata, e.g. for an NLE)", "set"),
            ("Burn in a running timecode window", "burn"),
        ],
        default="set",
    )

    if mode == "burn" and not hardware.has_filter("drawtext"):
        console.print(
            "This ffmpeg build can't draw a timecode window (drawtext needs libfreetype). "
            "`brew install ffmpeg-full` includes it.",
            style="ffx.error",
        )
        return None

    timecode = prompts.ask_text(
        "Start timecode:",
        default="01:00:00:00",
        validator=TimecodeValidator(),
        hint="HH:MM:SS:FF — 01:00:00:00 is the broadcast-common one-hour start.",
    )
    return {"mode": mode, "timecode": timecode}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    timecode = params.get("timecode", "01:00:00:00")

    if params["mode"] == "set":
        return OperationSettings(
            name=name,
            display_name=display_name,
            description=f"Set start timecode {timecode}",
            non_video_output_args=["-timecode", timecode],
            serializable={},
        )

    video = media.primary_video
    # drawtext's timecode option needs the frame rate to advance, and its
    # parser requires the colons escaped even inside quotes.
    rate = (video.avg_frame_rate or video.r_frame_rate) if video else ""
    rate = rate or "25"
    escaped = timecode.replace(":", r"\:").replace(";", r"\;")
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Burn timecode window from {timecode}",
        video_filter=[
            f"drawtext=timecode='{escaped}':rate={rate}:fontsize=h/16:fontcolor=white"
            ":box=1:boxcolor=black@0.5:boxborderw=8:x=(w-text_w)/2:y=h-text_h-20"
        ],
        serializable={},
    )
