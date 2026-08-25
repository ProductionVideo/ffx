from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rich.console import Console

from ffx import presets as preset_calc
from ffx.models import MediaInfo, Preset, StreamInfo
from ffx.runner import FFmpegCancelled, run_with_output
from ffx.ui import prompts

name = "analyse"
display_name = "Analyse"
description = "Inspect it — nothing changes"

_BLACK_RE = re.compile(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*([\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")
_FREEZE_START_RE = re.compile(r"lavfi\.freezedetect\.freeze_start:\s*([\d.]+)")
_FREEZE_END_RE = re.compile(r"lavfi\.freezedetect\.freeze_end:\s*([\d.]+)")
_FREEZE_DURATION_RE = re.compile(r"lavfi\.freezedetect\.freeze_duration:\s*([\d.]+)")
# showinfo logs one line per decoded frame - "i:" is the field-order flag
# (P/T/B = progressive/top-first/bottom-first), not to be confused with
# "type:" (I/P/B frame type) right after "iskey:" - the non-greedy .*?
# spans are there so field order in the line (which has shifted between
# ffmpeg versions before) doesn't break the match.
_FRAME_RE = re.compile(r"n:\s*(\d+).*?pts_time:([\d.-]+).*?\si:(\S+)\s+iskey:(\d)\s+type:(\w)")

# "Streams & chapters" is synthesized straight from the already-probed
# MediaInfo (no ffmpeg call), so it's instant - grouped with the other
# checks anyway since it's the one genuinely new thing Analyse can show
# beyond what's already visible the moment a file is picked (every audio/
# subtitle track, language, default/forced flags, chapter markers - not
# just the primary streams summary_rows() shows).
_CHECK_CHOICES = [
    ("Streams & chapters — every track, language, default/forced flags", "streams"),
    ("Frame data — frame count, I/P/B mix, GOP size, field order", "frames"),
    ("Black sections", "black"),
    ("Silent sections", "silence"),
    ("Frozen (static) sections", "freeze"),
]

PRESETS = [
    Preset(
        "Full QC report",
        "Every stream/chapter, frame data, plus black/silent/frozen section detection",
        {"checks": ["streams", "frames", "black", "silence", "freeze"]},
    ),
]


@dataclass
class FrameStats:
    total: int = 0
    # Frame-type letter (I/P/B, occasionally others) -> count, in the
    # order first seen - dict preserves that, which reads more naturally
    # than an alphabetized breakdown (I before P before B, matching a
    # GOP's own structure).
    type_counts: dict = field(default_factory=dict)
    keyframe_count: int = 0
    # None when fewer than 2 keyframes were seen - one GOP length isn't
    # an "average" of anything.
    avg_gop_frames: Optional[float] = None
    # "progressive" | "interlaced (top-field-first)" |
    # "interlaced (bottom-field-first)" | "mixed" | "" (no frames read)
    field_order: str = ""
    # Derived from the scanned frames' own pts_time span, independent of
    # whatever the container's stream header claims - the point of this
    # check is catching a mismatch (VFR, a wrong declared rate), not
    # re-reporting the same number summary_rows() already shows.
    measured_fps: Optional[float] = None


@dataclass
class QCFindings:
    black_sections: list[tuple[float, float, float]] = field(default_factory=list)
    # end/duration are None when the section runs through end-of-stream,
    # since ffmpeg only logs an "_end" event when the condition actually
    # stops before EOF.
    silence_sections: list[tuple[float, Optional[float], Optional[float]]] = field(
        default_factory=list
    )
    freeze_sections: list[tuple[float, Optional[float], Optional[float]]] = field(
        default_factory=list
    )
    frame_stats: Optional[FrameStats] = None


def prompt() -> dict:
    preset = prompts.choose_preset(PRESETS, message="Analyse — choose a report:")
    if preset is not None:
        return dict(preset.values)
    checks = prompts.multi_choose(
        "Which checks? (space to toggle, enter to confirm)",
        _CHECK_CHOICES,
        defaults=["streams", "frames", "black", "silence"],
    )
    return {"checks": checks}


def humanize_duration(seconds: float) -> str:
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
        ("Duration", humanize_duration(media.duration)),
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


def run_qc(path: Path, checks: list[str], duration: float = 0.0, console: Optional[Console] = None) -> QCFindings:
    findings = QCFindings()
    if "frames" in checks:
        stderr = _run_filter(
            path, duration, console, "Reading frame data",
            vf="showinfo", drop_audio=True,
        )
        findings.frame_stats = _parse_frame_stats(stderr)
    if "black" in checks:
        stderr = _run_filter(
            path, duration, console, "Checking for black sections",
            vf="blackdetect=d=0.1:pix_th=0.10", drop_audio=True,
        )
        findings.black_sections = [
            (float(s), float(e), float(d)) for s, e, d in _BLACK_RE.findall(stderr)
        ]
    if "silence" in checks:
        stderr = _run_filter(
            path, duration, console, "Checking for silent sections",
            af="silencedetect=n=-30dB:d=0.5", drop_video=True,
        )
        starts = [float(s) for s in _SILENCE_START_RE.findall(stderr)]
        ends = [(float(e), float(d)) for e, d in _SILENCE_END_RE.findall(stderr)]
        for i, start in enumerate(starts):
            end, dur = ends[i] if i < len(ends) else (None, None)
            findings.silence_sections.append((start, end, dur))
    if "freeze" in checks:
        stderr = _run_filter(
            path, duration, console, "Checking for frozen sections",
            vf="freezedetect=n=-60dB:d=0.5", drop_audio=True,
        )
        starts = [float(s) for s in _FREEZE_START_RE.findall(stderr)]
        ends = [float(e) for e in _FREEZE_END_RE.findall(stderr)]
        durations = [float(d) for d in _FREEZE_DURATION_RE.findall(stderr)]
        for i, start in enumerate(starts):
            end = ends[i] if i < len(ends) else None
            dur = durations[i] if i < len(durations) else None
            findings.freeze_sections.append((start, end, dur))
    return findings


def _parse_frame_stats(stderr: str) -> FrameStats:
    matches = _FRAME_RE.findall(stderr)
    stats = FrameStats()
    if not matches:
        return stats

    stats.total = len(matches)
    field_orders: set = set()
    keyframe_indices = []
    for n, _pts_time, i_field, iskey, ftype in matches:
        stats.type_counts[ftype] = stats.type_counts.get(ftype, 0) + 1
        field_orders.add(i_field)
        if iskey == "1":
            keyframe_indices.append(int(n))

    stats.keyframe_count = len(keyframe_indices)
    if len(keyframe_indices) >= 2:
        gaps = [b - a for a, b in zip(keyframe_indices, keyframe_indices[1:])]
        stats.avg_gop_frames = sum(gaps) / len(gaps)

    stats.field_order = _describe_field_order(field_orders)

    first_pts, last_pts = float(matches[0][1]), float(matches[-1][1])
    span = last_pts - first_pts
    if span > 0 and stats.total > 1:
        stats.measured_fps = (stats.total - 1) / span
    return stats


def _describe_field_order(field_orders: set) -> str:
    if field_orders <= {"P"}:
        return "progressive"
    if field_orders <= {"T"}:
        return "interlaced (top-field-first)"
    if field_orders <= {"B"}:
        return "interlaced (bottom-field-first)"
    return "mixed"


def section_stats(
    sections: list[tuple], duration: float
) -> tuple[int, float, float]:
    """(count, total affected seconds, percent of runtime) for a list of
    (start, end, ...) tuples - end is None for a section still running at
    end-of-stream, which counts through the clip's own duration."""
    count = len(sections)
    total = sum((end if end is not None else duration) - start for start, end, *_ in sections)
    percent = (total / duration * 100) if duration > 0 else 0.0
    return count, total, percent


def streams_rows(media: MediaInfo) -> list[tuple]:
    """(index, type, codec, language, flags, title) per stream - every
    stream, not just the primary video/audio pair summary_rows() shows."""
    rows = []
    for s in media.streams:
        flags = ", ".join(f for f, on in (("default", s.is_default), ("forced", s.is_forced)) if on)
        title = s.tags.get("title", "")
        detail = _stream_detail(s)
        rows.append((s.index, s.codec_type, detail, s.language or "-", flags or "-", title or "-"))
    return rows


def _stream_detail(s: StreamInfo) -> str:
    if s.is_video:
        return f"{s.codec_name}, {s.width}x{s.height}" if s.width else s.codec_name
    if s.is_audio:
        return f"{s.codec_name}, {s.channel_layout}" if s.channel_layout else s.codec_name
    return s.codec_name


def chapter_rows(media: MediaInfo) -> list[tuple[int, float, float, str]]:
    return [(c.index, c.start, c.end, c.title or "-") for c in media.chapters]


def _run_filter(
    path: Path,
    duration: float,
    console: Optional[Console],
    description: str,
    *,
    vf: str = "",
    af: str = "",
    drop_audio: bool = False,
    drop_video: bool = False,
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
    try:
        return run_with_output(args, total_duration=duration, console=console, description=description)
    except FFmpegCancelled:
        # Keep Ctrl+C meaning "bail out of the whole app" everywhere else
        # in ffx, rather than introducing a second, different cancel
        # behavior just for this scan.
        raise KeyboardInterrupt from None
