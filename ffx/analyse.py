from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ffx import presets as preset_calc
from ffx.models import MediaInfo, Preset
from ffx.ui import prompts

name = "analyse"
display_name = "Analyse"
description = "Inspect it — nothing changes"

_BLACK_RE = re.compile(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*([\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")
_FREEZE_START_RE = re.compile(r"lavfi\.freezedetect\.freeze_start:\s*([\d.]+)")
_FREEZE_END_RE = re.compile(r"lavfi\.freezedetect\.freeze_end:\s*([\d.]+)")

PRESETS = [
    Preset("Quick summary", "Format, codecs, resolution, framerate, duration", {"checks": []}),
    Preset(
        "Full QC report",
        "Quick summary plus black/silent/frozen section detection",
        {"checks": ["black", "silence", "freeze"]},
    ),
]


@dataclass
class QCFindings:
    black_sections: list[tuple[float, float, float]] = field(default_factory=list)
    # end/duration are None when the silence runs through end-of-stream,
    # since ffmpeg only logs silence_end when silence actually stops.
    silence_sections: list[tuple[float, Optional[float], Optional[float]]] = field(
        default_factory=list
    )
    freeze_starts: list[float] = field(default_factory=list)


def prompt() -> dict:
    preset = prompts.choose_preset(PRESETS, message="Analyse — choose a report:")
    if preset is not None:
        return dict(preset.values)
    checks = []
    if prompts.ask_confirm("Check for black sections?", default=True):
        checks.append("black")
    if prompts.ask_confirm("Check for silent sections?", default=True):
        checks.append("silence")
    if prompts.ask_confirm("Check for frozen (static) sections?", default=False):
        checks.append("freeze")
    return {"checks": checks}


def _humanize_duration(seconds: float) -> str:
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def summary_rows(media: MediaInfo) -> list[tuple[str, str]]:
    rows = [
        ("File", str(media.path)),
        ("Format", media.format_long_name or media.format_name),
        ("Duration", _humanize_duration(media.duration)),
        ("Size", preset_calc.humanize_size(media.size / 1024 / 1024)),
        ("Overall bitrate", f"{media.bit_rate // 1000} kbps" if media.bit_rate else "-"),
    ]
    if media.primary_video:
        v = media.primary_video
        rows += [
            ("Video codec", f"{v.codec_name} ({v.profile})" if v.profile else v.codec_name),
            ("Resolution", f"{v.width}x{v.height}"),
            ("Frame rate", f"{v.frame_rate} fps" if v.frame_rate else "-"),
            ("Pixel format", v.pix_fmt or "-"),
            ("Colour space", v.color_space or "-"),
        ]
    if media.primary_audio:
        a = media.primary_audio
        rows += [
            ("Audio codec", a.codec_name),
            ("Channels", f"{a.channels} ({a.channel_layout})" if a.channels else "-"),
            ("Sample rate", f"{a.sample_rate} Hz" if a.sample_rate else "-"),
        ]
    return rows


def run_qc(path: Path, checks: list[str]) -> QCFindings:
    findings = QCFindings()
    if "black" in checks:
        stderr = _run_filter(path, vf="blackdetect=d=0.1:pix_th=0.10", drop_audio=True)
        findings.black_sections = [
            (float(s), float(e), float(d)) for s, e, d in _BLACK_RE.findall(stderr)
        ]
    if "silence" in checks:
        stderr = _run_filter(path, af="silencedetect=n=-30dB:d=0.5", drop_video=True)
        starts = [float(s) for s in _SILENCE_START_RE.findall(stderr)]
        ends = [(float(e), float(d)) for e, d in _SILENCE_END_RE.findall(stderr)]
        for i, start in enumerate(starts):
            end, dur = ends[i] if i < len(ends) else (None, None)
            findings.silence_sections.append((start, end, dur))
    if "freeze" in checks:
        stderr = _run_filter(path, vf="freezedetect=n=-60dB:d=0.5", drop_audio=True)
        findings.freeze_starts = [float(s) for s in _FREEZE_START_RE.findall(stderr)]
    return findings


def _run_filter(
    path: Path, *, vf: str = "", af: str = "", drop_audio: bool = False, drop_video: bool = False
) -> str:
    args = ["ffmpeg", "-i", str(path)]
    if vf:
        args += ["-vf", vf]
    if af:
        args += ["-af", af]
    if drop_audio:
        args += ["-an"]
    if drop_video:
        args += ["-vn"]
    args += ["-f", "null", "-"]
    result = subprocess.run(args, capture_output=True, text=True, timeout=300)
    return result.stderr
