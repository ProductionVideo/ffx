from __future__ import annotations

from InquirerPy import get_style
from rich.console import Console
from rich.rule import Rule
from rich.theme import Theme

FFX_THEME = Theme(
    {
        "ffx.title": "bold cyan",
        "ffx.step": "bold magenta",
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
        "questionmark": "#00afff bold",
        "answermark": "#00afff bold",
        "answer": "#00afff",
        "input": "#00afff",
        "question": "bold",
        "answered_question": "bold",
        "pointer": "#00afff bold",
        "marker": "#00afff bold",
    },
    style_override=True,
)


def print_banner() -> None:
    console.print()
    console.print(" ffx ", style="reverse bold cyan", justify="left")
    console.print("beautiful ffmpeg, without the syntax — let's go", style="ffx.muted")
    console.print()


def print_step(number: int, total: int, title: str) -> None:
    console.print()
    console.print(Rule(f"[ffx.step]Step {number}/{total}[/ffx.step]  {title}", style="ffx.step", align="left"))
