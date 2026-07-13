from __future__ import annotations

# Shared by any operation that puts a free-form string (on-screen text, a
# file path) into an ffmpeg filter option. Wrapping in single quotes stops
# the avfilter parser from treating ':' or ',' inside the value as option/
# filter separators; the two characters that still need escaping even
# inside single quotes are backslash and the quote itself.
def quote_filter_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"
