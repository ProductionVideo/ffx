from __future__ import annotations

from InquirerPy import get_style
from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme
from rich import box

# One accent, used for exactly two jobs: things you interact with
# (InquirerPy prompts) and the border/badge of things that frame
# information (banner, step badges, data tables). It never colors body
# text - that stays plain bold, so the accent reads as a deliberate
# frame instead of a wash over everything.
_ACCENT = "#00afff"

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
            box=box.DOUBLE,
            border_style="ffx.accent",
            expand=False,
            padding=(0, 2),
        )
    )


def print_step(number: int, total: int, title: str) -> None:
    # A solid colored badge (same reverse-video move as the banner's "ffx"
    # chip) gives the eye one clear anchor per step, instead of a long
    # thin rule that reads as a flat gray wash across the terminal width.
    # A bare attribute keyword (reverse) combined with a custom theme name
    # in one tag silently produces no style at all in Rich - confirmed by
    # testing, not assumed - so this uses the raw accent hex directly
    # rather than the "ffx.accent" theme name.
    console.print()
    console.print(f"[reverse bold {_ACCENT}] {number}/{total} [/] [bold]{title}[/]", highlight=False)
