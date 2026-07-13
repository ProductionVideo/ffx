"""Modal prompt screens - the Textual counterparts of ffx.ui.prompts.

Every screen dismisses with a (value, back) tuple, matching the contract
of the render() closures inside ffx.ui.prompts, so the wizard back-stack
(run_wizard/GoBack) works identically in both UIs. Escape is "back" when
the prompt is inside a wizard, mirroring Ctrl+Z/Back in the classic UI.

Prompts render as a bottom sheet over an undimmed screen (rather than a
centered dialog) so the Media/Pipeline panes and the activity log stay
readable while answering - anything an operation prints (a warning, an
unavailability explanation) is visible right above the question.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, SelectionList, Static
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

_PANEL_CSS = """
PromptScreen {
    align: center bottom;
    background: $background 0%;
}
PromptScreen > Vertical {
    width: 100%;
    height: auto;
    max-height: 70%;
    border-top: thick $accent;
    background: $surface;
    padding: 1 2;
}
PromptScreen .prompt-message {
    text-style: bold;
    margin-bottom: 1;
}
PromptScreen .prompt-hint {
    color: $text-muted;
    margin-top: 1;
}
PromptScreen .prompt-error {
    color: $error;
}
PromptScreen OptionList, PromptScreen SelectionList {
    height: auto;
    max-height: 20;
    border: none;
    background: $surface;
}
"""


class PromptScreen(ModalScreen):
    """Shared frame: message on top, hint underneath, Escape = back."""

    DEFAULT_CSS = _PANEL_CSS
    BINDINGS = [Binding("escape", "back", "Back", show=True)]

    def __init__(self, message: str, *, hint: str = "", back_enabled: bool = False):
        super().__init__()
        self._message = message
        self._hint = hint
        self._back_enabled = back_enabled

    def compose(self) -> ComposeResult:
        hint = self._hint
        if self._back_enabled:
            hint = f"{hint}  (Esc: back)" if hint else "Esc: back"
        # Messages, labels, and hints are arbitrary strings (file names,
        # preset descriptions with [brackets]) - always Text, never markup.
        with Vertical():
            yield Label(Text(self._message), classes="prompt-message")
            yield from self.compose_body()
            if hint:
                yield Static(Text(hint), classes="prompt-hint")

    def compose_body(self) -> ComposeResult:
        yield from ()

    def action_back(self) -> None:
        if self._back_enabled:
            self.dismiss((None, True))


class SelectScreen(PromptScreen):
    """One-of-many pick; choices are (label, value) pairs."""

    def __init__(
        self,
        message: str,
        choices: list[tuple[str, Any]],
        *,
        default: Any = None,
        hint: str = "",
        back_enabled: bool = False,
    ):
        super().__init__(message, hint=hint, back_enabled=back_enabled)
        self._choices = choices
        self._default = default

    def compose_body(self) -> ComposeResult:
        yield OptionList(*[Option(Text(label)) for label, _ in self._choices])

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        for i, (_, value) in enumerate(self._choices):
            if value == self._default:
                option_list.highlighted = i
                break
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss((self._choices[event.option_index][1], False))


class TextScreen(PromptScreen):
    """Free-text entry with inline validation.

    `validate` returns an error message for bad input, or None to accept -
    the InquirerPy Validator objects are adapted to this shape by
    ffx.ui.prompts rather than leaking prompt_toolkit types in here.
    """

    def __init__(
        self,
        message: str,
        *,
        default: str = "",
        validate: Optional[Callable[[str], Optional[str]]] = None,
        hint: str = "",
        back_enabled: bool = False,
    ):
        super().__init__(message, hint=hint, back_enabled=back_enabled)
        self._default = default
        self._validate = validate

    def compose_body(self) -> ComposeResult:
        yield Input(value=self._default)
        yield Static("", classes="prompt-error")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._validate is not None:
            error = self._validate(event.value)
            if error:
                self.query_one(".prompt-error", Static).update(Text(error))
                return
        self.dismiss((event.value, False))


class _PathInput(Input):
    """An Input that un-mangles dropped/pasted paths as they land.

    Dragging a file from Finder (or Terminal's "Copy as Pathname") arrives
    quoted or backslash-escaped; cleaning it on paste means the box shows
    the real path immediately instead of `My\\ Movie.mp4`.
    """

    def _on_paste(self, event: events.Paste) -> None:
        from ffx.ui.prompts import clean_path_input

        self.insert_text_at_cursor(clean_path_input(event.text).strip())
        event.stop()
        event.prevent_default()


class PathScreen(TextScreen):
    """Path entry with a live preview line - drop a file in, see the
    resolved path (or "doesn't exist") before committing to Enter."""

    def __init__(
        self,
        message: str,
        *,
        default: str = "",
        must_exist: bool = False,
        hint: str = "",
        back_enabled: bool = False,
    ):
        self._must_exist = must_exist
        super().__init__(
            message,
            default=default,
            validate=self._check if must_exist else None,
            hint=hint or "Drag a file from Finder into this window, or type a path.",
            back_enabled=back_enabled,
        )

    def _check(self, text: str) -> Optional[str]:
        from ffx.ui.prompts import clean_path_input

        if not Path(clean_path_input(text)).expanduser().exists():
            return "That path doesn't exist"
        return None

    def compose_body(self) -> ComposeResult:
        yield _PathInput(value=self._default)
        yield Static("", classes="prompt-path-status")
        yield Static("", classes="prompt-error")

    def on_input_changed(self, event: Input.Changed) -> None:
        from ffx.ui.prompts import clean_path_input

        self.query_one(".prompt-error", Static).update("")
        status = self.query_one(".prompt-path-status", Static)
        text = clean_path_input(event.value or "").strip()
        if not text:
            status.update("")
            return
        path = Path(text).expanduser()
        if path.is_dir():
            status.update(Text(f"✓ folder: {path}", style="green"))
        elif path.exists():
            status.update(Text(f"✓ {path}", style="green"))
        elif self._must_exist:
            status.update(Text(f"✗ no such path: {path}", style="red"))
        else:
            status.update(Text(f"will be created: {path}", style="dim"))


class ConfirmScreen(PromptScreen):
    """Yes/no; y/n answer directly, Enter takes the default."""

    BINDINGS = PromptScreen.BINDINGS + [
        Binding("y", "answer(True)", "Yes"),
        Binding("n", "answer(False)", "No"),
        Binding("enter", "accept_default", "Default", priority=True),
    ]

    def __init__(self, message: str, *, default: bool = True, hint: str = "", back_enabled: bool = False):
        super().__init__(message, hint=hint, back_enabled=back_enabled)
        self._default = default

    def compose_body(self) -> ComposeResult:
        suffix = "[Y/n]" if self._default else "[y/N]"
        yield Static(f"{suffix}  (y / n, Enter = default)")

    def action_answer(self, value: bool) -> None:
        self.dismiss((value, False))

    def action_accept_default(self) -> None:
        self.dismiss((self._default, False))


class CheckScreen(PromptScreen):
    """Several-of-many pick; Space toggles, Enter confirms."""

    BINDINGS = PromptScreen.BINDINGS + [Binding("enter", "confirm", "Confirm", priority=True)]

    def __init__(
        self,
        message: str,
        choices: list[tuple[str, Any]],
        *,
        defaults: Optional[list[Any]] = None,
        hint: str = "",
        back_enabled: bool = False,
    ):
        super().__init__(message, hint=hint, back_enabled=back_enabled)
        self._choices = choices
        self._defaults = defaults or []

    def compose_body(self) -> ComposeResult:
        yield SelectionList(
            *[Selection(Text(label), value, value in self._defaults) for label, value in self._choices]
        )

    def on_mount(self) -> None:
        self.query_one(SelectionList).focus()

    def action_confirm(self) -> None:
        self.dismiss((list(self.query_one(SelectionList).selected), False))
