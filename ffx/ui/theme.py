from __future__ import annotations

from InquirerPy import get_style
from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme
from rich import box

# The interactive accent - the banner and the live selection cursor in
# InquirerPy prompts. Kept to those two spots deliberately: it used to also
# cover every table/panel border, the step badge, and every completed-answer
# echo, which made the whole app read as "blue" rather than colorful.
_ACCENT = "#00afff"

# The step badge ("2/5") gets its own hue, distinct from the accent and from
# every CATEGORY_COLORS entry, so it isn't just more blue.
_STEP_COLOR = "#ff5faf"

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
    "orientate": "#d7ff5f",
    "colour": "#ff5fd7",
    "text": "#5fffd7",
    "composite": "#af5fff",
    "sequence": "#87d75f",
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
        # Neutral square-box border for passive display (info/analysis
        # tables, the Pipeline panel) - the data inside already carries
        # CATEGORY_COLORS/FIELD_COLORS, so the frame doesn't need to compete.
        "ffx.border": "grey58",
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
        # Only the live cursor stays accent-blue (the "you are here"
        # indicator, consistent for the whole app). Everything that's just
        # been answered renders in plain bold instead of re-painting the
        # same blue down the transcript as you move through the wizard.
        "questionmark": f"{_ACCENT} bold",
        "answermark": "bold green",
        "answer": "bold",
        "input": "bold",
        "question": "bold",
        "answered_question": "bold",
        "pointer": f"{_ACCENT} bold",
        "marker": "bold green",
    },
    style_override=True,
)


def print_banner() -> None:
    console.print()
    console.print(
        Panel(
            "[bold]ffx[/bold]\n[ffx.muted]ffmpeg, for the simple[/ffx.muted]",
            box=box.SQUARE,
            border_style="ffx.accent",
            expand=False,
            padding=(0, 2),
        )
    )


def print_step(number: int, total: int, title: str) -> None:
    # A bare attribute keyword (reverse) combined with a custom theme name
    # in one tag silently produces no style at all in Rich (confirmed by
    # testing) - so this uses the raw hex directly. Its own hue (not the
    # accent) so the step badge doesn't add to the blue count.
    console.print()
    console.print(f"[reverse bold {_STEP_COLOR}] {number}/{total} [/] [bold]{title}[/]", highlight=False)
