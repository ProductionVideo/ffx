from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ffx.models import MediaInfo, StreamInfo


class ProbeError(RuntimeError):
    """Raised when ffprobe fails or a path isn't readable media."""


def probe(path: Path) -> MediaInfo:
    """Run ffprobe on `path` and parse the result into a MediaInfo."""
    args = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(f"could not run ffprobe on {path}: {exc}") from exc

    if result.returncode != 0:
        raise ProbeError(f"ffprobe failed on {path}: {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned invalid JSON for {path}: {exc}") from exc

    return _parse(path, data)


def _parse(path: Path, data: dict) -> MediaInfo:
    fmt = data.get("format", {})
    streams = [_parse_stream(s) for s in data.get("streams", [])]

    return MediaInfo(
        path=path,
        format_name=fmt.get("format_name", ""),
        format_long_name=fmt.get("format_long_name", ""),
        duration=_to_float(fmt.get("duration")) or 0.0,
        size=_to_int(fmt.get("size")) or 0,
        bit_rate=_to_int(fmt.get("bit_rate")) or 0,
        streams=streams,
        tags=fmt.get("tags", {}),
    )


def _parse_stream(s: dict) -> StreamInfo:
    return StreamInfo(
        index=s.get("index", 0),
        codec_type=s.get("codec_type", ""),
        codec_name=s.get("codec_name", ""),
        codec_long_name=s.get("codec_long_name", ""),
        profile=s.get("profile", ""),
        width=s.get("width"),
        height=s.get("height"),
        r_frame_rate=s.get("r_frame_rate", ""),
        avg_frame_rate=s.get("avg_frame_rate", ""),
        pix_fmt=s.get("pix_fmt", ""),
        color_space=s.get("color_space", ""),
        color_transfer=s.get("color_transfer", ""),
        color_primaries=s.get("color_primaries", ""),
        channels=s.get("channels"),
        channel_layout=s.get("channel_layout", ""),
        sample_rate=_to_int(s.get("sample_rate")),
        bit_depth=_to_int(s.get("bits_per_raw_sample")),
        bit_rate=_to_int(s.get("bit_rate")),
        duration=_to_float(s.get("duration")),
        tags=s.get("tags", {}),
    )


def _to_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
