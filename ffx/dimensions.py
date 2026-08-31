"""Best-effort tracking of a pipeline's frame size as operations queue up.

Every operation's prompt() only ever sees the file's own probed
dimensions - there's no notion of "what will the frame actually be by
the time *this* operation's filter runs," after whatever Scale/Crop/
Orientate steps are already queued ahead of it. That gap is exactly how
"scale to 1280 wide, then manually crop a 1600-wide rectangle" reaches
ffmpeg as a real, hard failure ("Failed to configure input pad") instead
of being caught as an invalid answer up front - confirmed by reproducing
it against real ffmpeg while building this fix.

Not every operation changes pixel dimensions, and this doesn't try to
model everything that might (Composite's stack modes, mainly) - an
operation this can't reason about is simply assumed to leave the frame
size unchanged, which is the common case and never makes an accurate
answer look wrong.
"""
from __future__ import annotations

import dataclasses

from ffx.models import MediaInfo


def effective_media(media: MediaInfo, ordered_ops: list) -> MediaInfo:
    """A copy of `media` with its primary video stream's width/height
    updated to the effective_size() after every operation in
    `ordered_ops` - every other field (audio, format, duration, tags,
    other streams) is untouched. Returns `media` itself, unchanged, when
    there's no video stream or nothing queued actually changes its size.
    """
    video = media.primary_video
    if video is None or not video.width or not video.height:
        return media

    size = effective_size(media, ordered_ops)
    if size is None or size == (video.width, video.height):
        return media

    updated_video = dataclasses.replace(video, width=size[0], height=size[1])
    streams = [updated_video if s is video else s for s in media.streams]
    return dataclasses.replace(media, streams=streams)


def effective_size(media: MediaInfo, ordered_ops: list) -> tuple[int, int] | None:
    """(width, height) after applying every queued operation's known
    effect on frame size, in order. None if the source has no video
    stream with known dimensions."""
    video = media.primary_video
    if video is None or not video.width or not video.height:
        return None
    w, h = video.width, video.height
    for module, params in ordered_ops:
        w, h = _apply(module.name, params, w, h)
    return w, h


def _apply(op_name: str, params: dict, w: int, h: int) -> tuple[int, int]:
    if op_name == "scale":
        return _apply_scale(params, w, h)
    if op_name == "crop":
        return _apply_crop(params, w, h)
    if op_name == "orientate":
        return _apply_orientate(params, w, h)
    return w, h


def _even(n: float) -> int:
    return max(2, round(n / 2) * 2)


def _apply_scale(params: dict, w: int, h: int) -> tuple[int, int]:
    # Mirrors scale.py's build() exactly - the "-2" ffmpeg passes for the
    # unspecified side there means "auto, keep aspect ratio, round even",
    # reproduced here instead of assumed.
    mode = params.get("mode")
    if mode == "width":
        target_w = params["width"]
        return target_w, _even(h * target_w / w)
    if mode == "height":
        target_h = params["height"]
        return _even(w * target_h / h), target_h
    if mode == "percent":
        fraction = params["percent"] / 100
        return _even(w * fraction), _even(h * fraction)
    if mode in ("fit", "fill", "stretch"):
        # All three land on an exact w x h canvas - fit pads to it, fill
        # crops to it, stretch forces it directly.
        return params["width"], params["height"]
    return w, h


def _apply_crop(params: dict, w: int, h: int) -> tuple[int, int]:
    # Mirrors crop.py's build()/_aspect_crop_filter() exactly.
    mode = params.get("mode")
    if mode == "rect":
        return params["width"], params["height"]
    if mode == "aspect":
        num, _, den = params["aspect"].partition(":")
        n, d = int(num), int(den)
        if w * d > h * n:  # w/h > n/d, cross-multiplied to avoid float drift
            return _even(h * n / d), h
        return w, _even(w * d / n)
    if mode == "border":
        t = params["thickness"]
        return w + 2 * t, h + 2 * t
    return w, h


def _apply_orientate(params: dict, w: int, h: int) -> tuple[int, int]:
    if params.get("mode") == "rotate" and params.get("angle") in (90, -90):
        return h, w
    return w, h
