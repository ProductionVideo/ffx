from __future__ import annotations

from ffx.operations import (
    colour, composite, convert, crop, cut, metadata, orientate, repair, scale, sequence, sound, text, time,
)

CATEGORIES = [convert, cut, scale, crop, orientate, colour, text, composite, sequence, time, sound, metadata, repair]

_BY_NAME = {module.name: module for module in CATEGORIES}


def get_operation(op_name: str):
    return _BY_NAME[op_name]
