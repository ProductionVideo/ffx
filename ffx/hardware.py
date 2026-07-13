from __future__ import annotations

import re
import subprocess
from functools import lru_cache

from ffx.models import HardwareCapabilities

_HWACCEL_ENCODER_RE = re.compile(r"^\s*V[A-Z.]*\s+(\S+_videotoolbox)\s", re.MULTILINE)

# `ffmpeg -filters` rows look like " T.. drawtext           V->V   Draw text ...":
# a flags column (T/S/C or '.'), the filter name, then an I/O spec containing
# "->". Some ffmpeg builds (notably Homebrew's default, non-"full" formula)
# are compiled without libfreetype/fontconfig and simply don't have
# `drawtext` at all - this is how operations that depend on an optional
# filter (Text) find out before asking the user anything.
_FILTER_RE = re.compile(r"^\s*\S{1,3}\s+(\S+)\s+\S*->\S*", re.MULTILINE)

# Unlike encoding, ffmpeg has no separate "*_videotoolbox" decoder names -
# VideoToolbox decode is applied generically via "-hwaccel videotoolbox" on
# top of the standard decoder, so it can't be discovered from `-decoders`
# output. This is the set VideoToolbox is known to accelerate on Apple
# Silicon; ffmpeg silently falls back to software if a specific stream
# (e.g. an unusual profile) isn't actually supported.
_KNOWN_VIDEOTOOLBOX_DECODE_CODECS = {
    "h264",
    "hevc",
    "prores",
    "mpeg2video",
    "mpeg4",
    "vp9",
}


@lru_cache(maxsize=1)
def detect() -> HardwareCapabilities:
    """Probe the local ffmpeg build once for VideoToolbox support.

    Cached per-process: hardware capabilities don't change mid-run, and
    this avoids re-spawning ffmpeg for every operation prompt that needs
    to know what codecs are available.
    """
    encoders_out = _run(["ffmpeg", "-hide_banner", "-encoders"])
    hwaccels_out = _run(["ffmpeg", "-hide_banner", "-hwaccels"])
    filters_out = _run(["ffmpeg", "-hide_banner", "-filters"])

    hw_encoders = {m.group(1) for m in _HWACCEL_ENCODER_RE.finditer(encoders_out)}
    videotoolbox_available = "videotoolbox" in hwaccels_out
    hw_decoders = set(_KNOWN_VIDEOTOOLBOX_DECODE_CODECS) if videotoolbox_available else set()
    filters = {m.group(1) for m in _FILTER_RE.finditer(filters_out)}

    return HardwareCapabilities(
        videotoolbox_available=videotoolbox_available,
        hw_encoders=hw_encoders,
        hw_decoders=hw_decoders,
        filters=filters,
    )


def _run(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""
