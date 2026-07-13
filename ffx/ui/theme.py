from __future__ import annotations

from InquirerPy import get_style
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.theme import Theme
from rich import box

# Accent reserved for things you actively interact with (InquirerPy
# prompts, the banner) - everything else leans on weight/box-drawing
# rather than color, so color stays meaningful instead of blanketing
# every line the same hue.
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
    console.print()
    console.print(Rule(f"[bold]Step {number}/{total}[/bold]  {title}", characters="━", style="ffx.muted", align="left"))
