from __future__ import annotations

from InquirerPy import get_style
from rich.console import Console
from rich.rule import Rule
from rich.theme import Theme

# One accent (a clean cyan-blue) used everywhere something is interactive
# or structural - InquirerPy's own accent, step rules, and the banner all
# match instead of competing (previously: blue prompts, magenta steps,
# an unused cyan "title" - three hues fighting for attention).
_ACCENT = "#00afff"

FFX_THEME = Theme(
    {
        "ffx.accent": f"bold {_ACCENT}",
        "ffx.step": f"bold {_ACCENT}",
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
    console.print(" ffx ", style=f"reverse bold {_ACCENT}", justify="left")
    console.print("beautiful ffmpeg, without the syntax — let's go", style="ffx.muted")
    console.print()


def print_step(number: int, total: int, title: str) -> None:
    console.print()
    console.print(Rule(f"[ffx.step]Step {number}/{total}[/ffx.step]  {title}", style="ffx.step", align="left"))
