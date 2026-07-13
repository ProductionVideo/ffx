from __future__ import annotations

from ffx.operations import (
    caption, colour, composite, convert, crop, cut, metadata, orientate, repair,
    scale, sequence, sound, text, thumbnail, time, timecode,
)

CATEGORIES = [
    convert, cut, scale, crop, thumbnail, orientate, colour, text, caption,
    timecode, composite, sequence, time, sound, metadata, repair,
]

_BY_NAME = {module.name: module for module in CATEGORIES}


def get_operation(op_name: str):
    return _BY_NAME[op_name]
