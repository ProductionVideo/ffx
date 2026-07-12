from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.validator import ValidationError, Validator

from ffx.models import Preset
from ffx.ui.theme import INQUIRER_STYLE

_TIMESTAMP_RE = re.compile(r"^(\d+(\.\d+)?|(\d{1,2}:)?\d{1,2}:\d{2}(\.\d+)?)$")


def clean_path_input(text: str) -> str:
    """Undo the quoting/escaping macOS adds when you paste a path.

    Finder's "Copy as Pathname" and Terminal's drag-and-drop both wrap or
    escape the path rather than giving back a plain string - e.g.
    `'/Users/jake/My Movie.mp4'` or `/Users/jake/My\\ Movie.mp4`. Accept
    those forms as well as a bare path.
    """
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return re.sub(r"\\(.)", r"\1", text)


class TimestampValidator(Validator):
    def validate(self, document) -> None:
        if not _TIMESTAMP_RE.match(document.text.strip()):
            raise ValidationError(
                message="Enter seconds (e.g. 12.5) or HH:MM:SS(.ms) (e.g. 00:01:30)",
                cursor_position=len(document.text),
            )


class ExistingPathValidator(Validator):
    def validate(self, document) -> None:
        if not Path(clean_path_input(document.text)).expanduser().exists():
            raise ValidationError(
                message="That path doesn't exist",
                cursor_position=len(document.text),
            )


def choose_preset(presets: list[Preset], *, message: str = "Choose a preset:") -> Optional[Preset]:
    """Show curated presets plus a trailing 'Custom...' option.

    Returns the chosen Preset, or None if the user picked Custom - the
    caller should then fall through to its full granular prompt flow.
    """
    choices = [Choice(value=p, name=f"{p.name}  [{p.description}]") for p in presets]
    choices.append(Choice(value=None, name="Custom... (set every option yourself)"))
    return inquirer.select(
        message=message,
        choices=choices,
        style=INQUIRER_STYLE,
        qmark="?",
    ).execute()


def choose(message: str, choices: list[tuple[str, Any]]) -> Any:
    """Generic menu: choices is a list of (label, value) pairs."""
    return inquirer.select(
        message=message,
        choices=[Choice(value=value, name=label) for label, value in choices],
        style=INQUIRER_STYLE,
        qmark="?",
    ).execute()


def ask_text(message: str, *, default: str = "", validator: Optional[Validator] = None) -> str:
    return inquirer.text(
        message=message,
        default=default,
        validate=validator,
        style=INQUIRER_STYLE,
        qmark="?",
    ).execute()


def ask_timestamp(message: str, *, default: str = "0") -> str:
    return ask_text(message, default=default, validator=TimestampValidator())


def ask_confirm(message: str, *, default: bool = True) -> bool:
    return inquirer.confirm(
        message=message,
        default=default,
        style=INQUIRER_STYLE,
        qmark="?",
    ).execute()


def ask_existing_path(message: str, *, default: str = "") -> Path:
    raw = inquirer.filepath(
        message=message,
        default=default,
        validate=ExistingPathValidator(),
        filter=clean_path_input,
        style=INQUIRER_STYLE,
        qmark="?",
    ).execute()
    return Path(raw).expanduser().resolve()


def ask_output_path(message: str, *, default: str = "") -> Path:
    raw = inquirer.filepath(
        message=message,
        default=default,
        filter=clean_path_input,
        style=INQUIRER_STYLE,
        qmark="?",
    ).execute()
    return Path(raw).expanduser().resolve()
