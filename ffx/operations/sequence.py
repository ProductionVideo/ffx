from __future__ import annotations

from pathlib import Path

from ffx import probe
from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings
from ffx.ui import prompts
from ffx.ui.theme import console

name = "sequence"
display_name = "Sequence"
description = "Join clips end to end"


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    paths: list[str] = []
    while True:
        path = prompts.ask_existing_path("Path to the next clip to append:")
        paths.append(str(path))
        if not prompts.ask_confirm("Add another clip after that?", default=False):
            break

    # The concat filter needs an audio chain from every input or none -
    # decide once here (probing each appended clip) rather than failing
    # deep inside ffmpeg with a cryptic stream-count error.
    clips = [probe.probe(Path(p)) for p in paths]
    audio = media.primary_audio is not None and all(c.primary_audio for c in clips)
    if not audio and (media.primary_audio or any(c.primary_audio for c in clips)):
        console.print(
            "Not every clip has audio, so the joined result will be silent.",
            style="ffx.warn",
        )
    return {"paths": paths, "audio": audio}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    paths = [Path(p) for p in params["paths"]]
    audio = bool(params.get("audio", False))
    total = 1 + len(paths)

    # Every clip is conformed to the first clip's canvas and frame rate
    # (letterboxed, never stretched) - concat requires identical stream
    # parameters and "match the main input" is the least surprising rule.
    video = media.primary_video
    width = (video.width if video and video.width else 1920) // 2 * 2
    height = (video.height if video and video.height else 1080) // 2 * 2
    fps = (video.frame_rate if video else None) or 30

    chains = []
    joins = []
    for position in range(total):
        source = "0:v" if position == 0 else f"{{in{position - 1}}}:v"
        chains.append(
            f"[{source}]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{position}]"
        )
        joins.append(f"[v{position}]")
        if audio:
            joins.append(f"[0:a]" if position == 0 else f"[{{in{position - 1}}}:a]")

    fc = (
        ";".join(chains)
        + f";{''.join(joins)}concat=n={total}:v=1:a={1 if audio else 0}"
        + ("[outv][outa]" if audio else "[outv]")
    )
    output_args = ["-map", "[outv]"] + (["-map", "[outa]"] if audio else [])

    clip_names = ", ".join(p.name for p in paths)
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Join with {clip_names} ({total} clips{'' if audio else ', silent'})",
        extra_inputs=paths,
        extra_input_args=[[] for _ in paths],
        filter_complex=fc,
        output_args=output_args,
        serializable={},
    )
