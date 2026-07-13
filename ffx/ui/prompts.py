from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.validator import ValidationError, Validator

from ffx.models import Preset
from ffx.ui.theme import INQUIRER_STYLE

_TIMESTAMP_RE = re.compile(r"^(\d+(\.\d+)?|(\d{1,2}:)?\d{1,2}:\d{2}(\.\d+)?)$")

# Sentinel value for the explicit "← Back" menu item on select-style
# prompts (as opposed to Ctrl+Z "skip", used on free-text prompts where
# there's no list to add a row to - both funnel into the same GoBack).
#
# A plain `object()` doesn't survive the round-trip: InquirerPy copies
# Choice values internally, so an identity check (`is BACK`) always comes
# back False even when this exact item was picked (confirmed directly -
# the same underlying issue as the Preset-identity bug in choose_preset
# below). A string sentinel compared with `==` survives that copy fine.
BACK = "\x00ffx:back\x00"


class GoBack(Exception):
    """Raised internally when a prompt reports the user asked to go back.

    Only ever caught by run_wizard() - if this escapes it, something
    outside a run_wizard() call is trying to use a back-aware prompt.
    """


class _Wizard:
    """One back-stack for one run_wizard() call.

    Each prompts.* call made while this wizard is active is a "step".
    Answers are recorded in order. Going back pops the most recent one
    and the whole wrapped function is simply called again from the top -
    already-answered steps replay instantly from history instead of
    re-prompting, so only the popped step (and anything after it) is
    actually re-asked.
    """

    def __init__(self) -> None:
        self.history: list[Any] = []
        self.pos = 0

    def begin_pass(self) -> None:
        self.pos = 0

    def step(self, render: Callable[[], tuple[Any, bool]]) -> Any:
        if self.pos < len(self.history):
            value = self.history[self.pos]
            self.pos += 1
            return value
        value, back = render()
        if back:
            raise GoBack()
        self.history.append(value)
        self.pos = len(self.history)
        return value

    def pop(self) -> bool:
        if not self.history:
            return False
        self.history.pop()
        self.pos = len(self.history)
        return True


_current: Optional[_Wizard] = None


def run_wizard(fn: Callable[..., Any], *args, **kwargs) -> Any:
    """Run `fn` (an operation's prompt(), or a single prompts.* call) with
    step-back support.

    Every prompts.* call made inside `fn`, however deeply nested,
    transparently gains a "go back" option - re-asking the previous
    question rather than the current one. Backing out of the very first
    question aborts entirely and this returns None, which callers should
    treat as "the user backed out of this whole step".

    Nests correctly: a run_wizard() call started from inside `fn` (e.g.
    __main__ wrapping one operation's whole prompt(), itself just one
    step of the outer flow) gets its own independent back-stack, and
    backing out of *that* inner flow's first question doesn't touch the
    outer one's history.
    """
    global _current
    wiz = _Wizard()
    previous = _current
    _current = wiz
    try:
        while True:
            wiz.begin_pass()
            try:
                return fn(*args, **kwargs)
            except GoBack:
                if not wiz.pop():
                    return None
    finally:
        _current = previous


def _step(render: Callable[[], tuple[Any, bool]]) -> Any:
    if _current is None:
        value, _ = render()
        return value
    return _current.step(render)


def _back_hint(hint: str) -> str:
    if _current is None:
        return hint
    extra = "Ctrl+Z: back"
    return f"{hint} ({extra})" if hint else extra


class _NumberValidator(Validator):
    def __init__(self, *, kind: type, min_allowed: Optional[float] = None, max_allowed: Optional[float] = None):
        self._kind = kind
        self._min = min_allowed
        self._max = max_allowed

    def validate(self, document) -> None:
        text = document.text.strip()
        try:
            value = self._kind(text)
        except ValueError:
            noun = "a whole number" if self._kind is int else "a number"
            raise ValidationError(message=f"Enter {noun}", cursor_position=len(document.text)) from None
        if self._min is not None and value < self._min:
            raise ValidationError(message=f"Must be at least {self._min}", cursor_position=len(document.text))
        if self._max is not None and value > self._max:
            raise ValidationError(message=f"Must be at most {self._max}", cursor_position=len(document.text))


def clean_path_input(text: Optional[str]) -> Optional[str]:
    """Undo the quoting/escaping macOS adds when you paste a path.

    Finder's "Copy as Pathname" and Terminal's drag-and-drop both wrap or
    escape the path rather than giving back a plain string - e.g.
    `'/Users/jake/My Movie.mp4'` or `/Users/jake/My\\ Movie.mp4`. Accept
    those forms as well as a bare path.

    InquirerPy runs this `filter` unconditionally, even when the prompt
    was skipped (Ctrl+Z, used for "back") rather than answered - in that
    case `text` is None, and there's no path to clean, so pass it through
    as-is instead of crashing on `.strip()`.
    """
    if text is None:
        return None
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


class RatioValidator(Validator):
    _RATIO_RE = re.compile(r"^\d+:\d+$")

    def validate(self, document) -> None:
        if not self._RATIO_RE.match(document.text.strip()):
            raise ValidationError(
                message="Enter a ratio like 16:9",
                cursor_position=len(document.text),
            )


def choose_preset(presets: list[Preset], *, message: str = "Choose a preset:") -> Optional[Preset]:
    """Show curated presets plus a trailing 'Custom...' option.

    Returns the chosen Preset, or None if the user picked Custom - the
    caller should then fall through to its full granular prompt flow.

    Selection is by index rather than handing the Preset object itself to
    InquirerPy as the Choice value: a dataclass instance round-tripped
    through the select prompt has been observed coming back as a plain
    dict, which breaks any caller that expects a Preset.
    """

    def render():
        choices = [Choice(value=i, name=f"{p.name}  [{p.description}]") for i, p in enumerate(presets)]
        choices.append(Choice(value=-1, name="Custom... (set every option yourself)"))
        if _current is not None:
            choices.append(Choice(value=BACK, name="Back"))
        index = inquirer.select(
            message=message,
            choices=choices,
            default=choices[0].value,
            style=INQUIRER_STYLE,
            qmark="?",
        ).execute()
        return index, index == BACK

    index = _step(render)
    return presets[index] if index >= 0 else None


def choose(
    message: str,
    choices: list[tuple[str, Any]],
    *,
    default: Any = None,
    hint: str = "",
) -> Any:
    """Generic menu: choices is a list of (label, value) pairs.

    `default` pre-highlights the matching choice so the common/fast path
    is just pressing Enter, while every option is still one arrow-key
    away - speed and full manual control aren't in tension.

    `hint` renders as a dim subtitle under the question (InquirerPy's
    long_instruction) - context that would otherwise have to get crammed
    into every choice label goes here once instead.
    """

    def render():
        items = [Choice(value=value, name=label) for label, value in choices]
        if _current is not None:
            items.append(Choice(value=BACK, name="Back"))
        result = inquirer.select(
            message=message,
            choices=items,
            default=default,
            long_instruction=hint,
            style=INQUIRER_STYLE,
            qmark="?",
        ).execute()
        return result, result == BACK

    return _step(render)


def ask_text(message: str, *, default: str = "", validator: Optional[Validator] = None, hint: str = "") -> str:
    def render():
        back_enabled = _current is not None
        prompt_obj = inquirer.text(
            message=message,
            default=default,
            validate=validator,
            long_instruction=_back_hint(hint),
            style=INQUIRER_STYLE,
            qmark="?",
            mandatory=not back_enabled,
        )
        result = prompt_obj.execute()
        return result, back_enabled and prompt_obj.status.get("skipped", False)

    return _step(render)


def ask_timestamp(message: str, *, default: str = "0") -> str:
    return ask_text(message, default=default, validator=TimestampValidator())


def ask_int(
    message: str,
    *,
    default: int,
    min_allowed: Optional[int] = None,
    max_allowed: Optional[int] = None,
    hint: str = "",
) -> int:
    """Plain text entry validated as an integer inline, instead of letting
    a bad `int(ask_text(...))` crash the whole run with a traceback.

    (InquirerPy's dedicated `number` prompt was tried and rejected here -
    it edits a fixed-point buffer digit-by-digit rather than accepting
    normal typed input, so typing "45" over a default of "20" produces
    "2045", not "45".)
    """
    value = ask_text(
        message,
        default=str(default),
        validator=_NumberValidator(kind=int, min_allowed=min_allowed, max_allowed=max_allowed),
        hint=hint,
    )
    return int(value)


def ask_float(
    message: str,
    *,
    default: float,
    min_allowed: Optional[float] = None,
    max_allowed: Optional[float] = None,
    hint: str = "",
) -> float:
    value = ask_text(
        message,
        default=str(default),
        validator=_NumberValidator(kind=float, min_allowed=min_allowed, max_allowed=max_allowed),
        hint=hint,
    )
    return float(value)


def multi_choose(
    message: str,
    choices: list[tuple[str, Any]],
    *,
    defaults: Optional[list[Any]] = None,
    hint: str = "",
) -> list[Any]:
    """Checkbox multi-select: space toggles, enter confirms - for picking
    several independent options in one screen instead of a chain of
    yes/no questions.

    A checkbox list mixing toggle-able items with a "go back" row would
    be confusing, so back (when available) is Ctrl+Z rather than a choice.
    """
    defaults = defaults or []

    def render():
        back_enabled = _current is not None
        items = [Choice(value=value, name=label, enabled=value in defaults) for label, value in choices]
        prompt_obj = inquirer.checkbox(
            message=message,
            choices=items,
            long_instruction=_back_hint(hint),
            style=INQUIRER_STYLE,
            qmark="?",
            mandatory=not back_enabled,
        )
        result = prompt_obj.execute()
        return result, back_enabled and prompt_obj.status.get("skipped", False)

    return _step(render)


def ask_confirm(message: str, *, default: bool = True, hint: str = "") -> bool:
    def render():
        back_enabled = _current is not None
        prompt_obj = inquirer.confirm(
            message=message,
            default=default,
            long_instruction=_back_hint(hint),
            style=INQUIRER_STYLE,
            qmark="?",
            mandatory=not back_enabled,
        )
        result = prompt_obj.execute()
        return result, back_enabled and prompt_obj.status.get("skipped", False)

    return _step(render)


def ask_existing_path(message: str, *, default: str = "") -> Path:
    def render():
        back_enabled = _current is not None
        prompt_obj = inquirer.filepath(
            message=message,
            default=default,
            validate=ExistingPathValidator(),
            filter=clean_path_input,
            long_instruction=_back_hint(""),
            style=INQUIRER_STYLE,
            qmark="?",
            mandatory=not back_enabled,
        )
        result = prompt_obj.execute()
        return result, back_enabled and prompt_obj.status.get("skipped", False)

    raw = _step(render)
    return Path(raw).expanduser().resolve()


def ask_output_path(message: str, *, default: str = "") -> Path:
    def render():
        back_enabled = _current is not None
        prompt_obj = inquirer.filepath(
            message=message,
            default=default,
            filter=clean_path_input,
            long_instruction=_back_hint(""),
            style=INQUIRER_STYLE,
            qmark="?",
            mandatory=not back_enabled,
        )
        result = prompt_obj.execute()
        return result, back_enabled and prompt_obj.status.get("skipped", False)

    raw = _step(render)
    return Path(raw).expanduser().resolve()
