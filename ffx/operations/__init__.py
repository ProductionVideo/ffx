from __future__ import annotations

from ffx.operations import convert, crop, cut, metadata, repair, scale, sound, time

CATEGORIES = [convert, cut, scale, crop, time, sound, metadata, repair]

_BY_NAME = {module.name: module for module in CATEGORIES}


def get_operation(op_name: str):
    return _BY_NAME[op_name]
