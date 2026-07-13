from __future__ import annotations

from InquirerPy import get_style
from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme
from rich import box

# The interactive accent - InquirerPy prompts, the banner, step badges.
_ACCENT = "#00afff"

# A distinct, deliberate hue per operation category (lazygit/btop-style:
# many saturated colors used meaningfully, not one flat accent repeated
# everywhere). Used for category icons in menus and the Pipeline panel,
# so the list of queued operations reads as genuinely colorful rather
# than a wash of bold white with a single accent border.
CATEGORY_COLORS = {
    "convert": "#5fd7ff",
    "cut": "#ff5f5f",
    "scale": "#d787ff",
    "crop": "#af87ff",
    "time": "#ffd75f",
    "sound": "#5fd787",
    "metadata": "#5f87ff",
    "repair": "#ff8700",
}

# A small set of hues for the "headline" facts in the media-info/analysis
# tables (duration, resolution, codec, bitrate) - the rest stay plain
# bold. Colors the data that's actually worth a glance instead of every
# row or none of them.
FIELD_COLORS = {
    "Duration": "#5fd7ff",
    "Resolution": "#d787ff",
    "Video codec": "#5fd787",
    "Audio codec": "#5fd787",
    "Overall bitrate": "#ffd75f",
    "Size": "#ffd75f",
    "Frame rate": "#ff8700",
}

FFX_THEME = Theme(
    {
        "ffx.accent": f"bold {_ACCENT}",
        "ffx.muted": "dim",
        "ffx.ok": "bold green",
        "ffx.warn": "bold yellow",
        "ffx.error": "bold red",
        "ffx.command": "italic grey70",
    }
)

console = Console(theme=FFX_THEME)

INQUIRER_STYLE = get_style(
    {
        "questionmark": f"{_ACCENT} bold",
        "answermark": f"{_ACCENT} bold",
        "answer": _ACCENT,
        "input": _ACCENT,
        "question": "bold",
        "answered_question": "bold",
        "pointer": f"{_ACCENT} bold",
        "marker": f"{_ACCENT} bold",
    },
    style_override=True,
)


def print_banner() -> None:
    console.print()
    console.print(
        Panel(
            "[bold]ffx[/bold]\n[ffx.muted]beautiful ffmpeg, without the syntax — let's go[/ffx.muted]",
            box=box.SQUARE,
            border_style="ffx.accent",
            expand=False,
            padding=(0, 2),
        )
    )


def print_step(number: int, total: int, title: str) -> None:
    # A bare attribute keyword (reverse) combined with a custom theme name
    # in one tag silently produces no style at all in Rich (confirmed by
    # testing) - so this uses the raw accent hex directly.
    console.print()
    console.print(f"[reverse bold {_ACCENT}] {number}/{total} [/] [bold]{title}[/]", highlight=False)
