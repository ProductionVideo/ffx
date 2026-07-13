from __future__ import annotations

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings
from ffx.ui import prompts
from ffx.ui.theme import console

name = "filters"
display_name = "Filters"
description = "Stock effects — sharpen, denoise, grain, vignette, stabilize..."

# The catalogue. Each entry: the ffmpeg filter it needs (gated per-build,
# like Text/HAP), an ask() for its one or two meaningful knobs, and a
# build() from those params to a -vf fragment. Queue the operation more
# than once to stack effects.
_EFFECTS: dict[str, dict] = {
    "deinterlace": {
        "label": "Deinterlace — fix combing from interlaced sources",
        "filter": "yadif",
        "ask": lambda media: {},
        "build": lambda p, media: ("yadif", "Deinterlace"),
    },
    "sharpen": {
        "label": "Sharpen",
        "filter": "unsharp",
        "ask": lambda media: {
            "amount": prompts.ask_float("Strength (0.2 subtle — 3 heavy):", default=1.0, min_allowed=0.2, max_allowed=3.0)
        },
        "build": lambda p, media: (f"unsharp=5:5:{p.get('amount', 1.0)}", f"Sharpen ({p.get('amount', 1.0):g})"),
    },
    "blur": {
        "label": "Blur (gaussian)",
        "filter": "gblur",
        "ask": lambda media: {
            "sigma": prompts.ask_float("Blur amount (sigma, 1 soft — 50 heavy):", default=5.0, min_allowed=0.5, max_allowed=50.0)
        },
        "build": lambda p, media: (f"gblur=sigma={p.get('sigma', 5.0)}", f"Blur (σ={p.get('sigma', 5.0):g})"),
    },
    "denoise": {
        "label": "Denoise — clean up sensor noise / compression fuzz",
        "filter": "hqdn3d",
        "ask": lambda media: {
            "level": prompts.choose(
                "How aggressively?",
                [("Light", "light"), ("Medium", "medium"), ("Strong (can smear detail)", "strong")],
                default="medium",
            )
        },
        "build": lambda p, media: (
            {"light": "hqdn3d=2:1:2:3", "medium": "hqdn3d", "strong": "hqdn3d=8:6:12:9"}[p.get("level", "medium")],
            f"Denoise ({p.get('level', 'medium')})",
        ),
    },
    "deband": {
        "label": "Deband — smooth gradient banding in skies/flat areas",
        "filter": "deband",
        "ask": lambda media: {},
        "build": lambda p, media: ("deband", "Deband"),
    },
    "grain": {
        "label": "Film grain",
        "filter": "noise",
        "ask": lambda media: {
            "strength": prompts.ask_int("Grain strength (5 subtle — 50 heavy):", default=12, min_allowed=1, max_allowed=100)
        },
        "build": lambda p, media: (
            f"noise=alls={p.get('strength', 12)}:allf=t+u",
            f"Film grain ({p.get('strength', 12)})",
        ),
    },
    "vignette": {
        "label": "Vignette — darkened corners",
        "filter": "vignette",
        "ask": lambda media: {},
        "build": lambda p, media: ("vignette", "Vignette"),
    },
    "sepia": {
        "label": "Sepia tone",
        "filter": "colorchannelmixer",
        "ask": lambda media: {},
        "build": lambda p, media: (
            "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
            "Sepia",
        ),
    },
    "pixelate": {
        "label": "Pixelate — mosaic censor/retro look",
        "filter": "pixelize",
        "ask": lambda media: {
            "block": prompts.ask_int("Block size (px):", default=16, min_allowed=2, max_allowed=128)
        },
        "build": lambda p, media: (
            f"pixelize=w={p.get('block', 16)}:h={p.get('block', 16)}",
            f"Pixelate ({p.get('block', 16)}px)",
        ),
    },
    "edges": {
        "label": "Edge sketch — line-art outline of the image",
        "filter": "edgedetect",
        "ask": lambda media: {},
        "build": lambda p, media: ("edgedetect", "Edge sketch"),
    },
    "aberration": {
        "label": "Chromatic aberration — RGB fringe glitch look",
        "filter": "chromashift",
        "ask": lambda media: {
            "shift": prompts.ask_int("Shift (px):", default=6, min_allowed=1, max_allowed=40)
        },
        "build": lambda p, media: (
            f"chromashift=cbh={p.get('shift', 6)}:crh=-{p.get('shift', 6)}",
            f"Chromatic aberration ({p.get('shift', 6)}px)",
        ),
    },
    "stabilize": {
        "label": "Stabilize — smooth out handheld shake",
        "filter": "deshake",
        "ask": lambda media: {},
        "build": lambda p, media: ("deshake", "Stabilize"),
    },
    "fade": {
        "label": "Fade the video in/out from black",
        "filter": "fade",
        "ask": lambda media: {
            "fade_in": prompts.ask_float("Fade in (seconds, 0 for none):", default=1.0, min_allowed=0),
            "fade_out": prompts.ask_float("Fade out (seconds, 0 for none):", default=1.0, min_allowed=0),
        },
        "build": None,  # special-cased: needs the clip duration and audio
    },
    "straighten": {
        "label": "Straighten — rotate by a small angle",
        "filter": "rotate",
        "ask": lambda media: {
            "degrees": prompts.ask_float("Degrees (negative = counter-clockwise):", default=2.0, min_allowed=-45, max_allowed=45)
        },
        "build": lambda p, media: (
            f"rotate={p.get('degrees', 2.0)}*PI/180:fillcolor=black",
            f"Straighten ({p.get('degrees', 2.0):g}°)",
        ),
    },
}


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict | None:
    menu = []
    for key, effect in _EFFECTS.items():
        label = effect["label"]
        if hardware.filters and not hardware.has_filter(effect["filter"]):
            label += f"  [unavailable: this ffmpeg lacks {effect['filter']}]"
        menu.append((label, key))

    effect_key = prompts.choose("Which effect?", menu, hint="Queue Filters again to stack effects.")
    effect = _EFFECTS[effect_key]
    if hardware.filters and not hardware.has_filter(effect["filter"]):
        console.print(
            f"This ffmpeg build doesn't have the '{effect['filter']}' filter.",
            style="ffx.error",
        )
        return None

    params = effect["ask"](media)
    return {"effect": effect_key, **params}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    effect_key = params["effect"]

    if effect_key == "fade":
        return _build_fade(params, media)

    fragment, label = _EFFECTS[effect_key]["build"](params, media)
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=label,
        video_filter=[fragment],
        serializable={},
    )


def _build_fade(params: dict, media: MediaInfo) -> OperationSettings:
    fade_in = params.get("fade_in", 1.0)
    fade_out = params.get("fade_out", 1.0)
    duration = media.duration or 0.0

    video_filter = []
    audio_filter = []
    if fade_in > 0:
        video_filter.append(f"fade=t=in:st=0:d={fade_in}")
        if media.primary_audio:
            audio_filter.append(f"afade=t=in:st=0:d={fade_in}")
    if fade_out > 0 and duration > fade_out:
        start = duration - fade_out
        video_filter.append(f"fade=t=out:st={start:.3f}:d={fade_out}")
        if media.primary_audio:
            audio_filter.append(f"afade=t=out:st={start:.3f}:d={fade_out}")

    parts = []
    if fade_in > 0:
        parts.append(f"in {fade_in:g}s")
    if fade_out > 0:
        parts.append(f"out {fade_out:g}s")
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Fade {' / '.join(parts) or '(none)'}",
        video_filter=video_filter,
        audio_filter=audio_filter,
        serializable={},
    )
