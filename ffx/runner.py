from __future__ import annotations

import selectors
import subprocess
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from ffx.ui.theme import FFX_THEME


class FFmpegRunError(RuntimeError):
    def __init__(self, returncode: int, stderr_tail: str):
        self.returncode = returncode
        self.stderr_tail = stderr_tail
        super().__init__(f"ffmpeg exited with code {returncode}")


class FFmpegCancelled(RuntimeError):
    """Raised when the user interrupts a running encode (Ctrl+C)."""


def run(
    argv: list[str],
    *,
    total_duration: float,
    console: Console | None = None,
    description: str = "Encoding",
    cleanup_on_cancel: bool = True,
) -> None:
    """Execute an ffmpeg argv, showing a rich progress bar.

    `total_duration` (seconds) is the expected output duration, used to
    turn ffmpeg's machine-readable progress stream into a percentage.
    Pass 0 if unknown (e.g. concat/analyse-adjacent jobs) and the bar
    falls back to an indeterminate spinner-style display.

    Ctrl+C cleanly kills the ffmpeg child (rather than leaving it running
    as an orphan) and deletes the partial output file, then raises
    FFmpegCancelled instead of letting a raw KeyboardInterrupt traceback
    reach the user. Pass `cleanup_on_cancel=False` for a 2-pass encode's
    analysis pass, whose "output" is /dev/null - there's nothing real to
    delete, and unlinking it would just raise a PermissionError.
    """
    console = console or Console(theme=FFX_THEME)
    output_path = Path(argv[-1])

    try:
        returncode, stderr_lines = _drive_with_progress(
            argv, total_duration=total_duration, console=console, description=description
        )
    except KeyboardInterrupt:
        if cleanup_on_cancel:
            output_path.unlink(missing_ok=True)
        raise FFmpegCancelled("cancelled by user") from None

    if returncode != 0:
        raise FFmpegRunError(returncode, "".join(stderr_lines[-40:]))


def run_with_output(
    argv: list[str],
    *,
    total_duration: float,
    console: Console | None = None,
    description: str = "Working",
) -> str:
    """Run an ffmpeg invocation whose useful result is its stderr text -
    QC filters like blackdetect/silencedetect/freezedetect (Analyse), or
    cropdetect (Crop's auto-detect) - rather than a produced file.

    Shows the same progress bar as run(), but returns the captured
    stderr instead of raising on the process's own exit code: these
    scans write to a null sink and routinely report their findings via
    stderr regardless of exit status, so there's no output file to clean
    up and no "failure" to distinguish from a successful scan.
    """
    console = console or Console(theme=FFX_THEME)
    try:
        _returncode, stderr_lines = _drive_with_progress(
            argv, total_duration=total_duration, console=console, description=description
        )
    except KeyboardInterrupt:
        raise FFmpegCancelled("cancelled by user") from None
    return "".join(stderr_lines)


def _drive_with_progress(
    argv: list[str],
    *,
    total_duration: float,
    console: Console,
    description: str,
) -> tuple[int, list[str]]:
    """Runs ffmpeg with a progress bar, returning (returncode, stderr_lines).

    Shared by run() and run_with_output() - they differ only in what they
    do with the result (raise + clean up an output file on failure, vs.
    just handing back the captured stderr regardless of exit status).
    """
    progress_argv = [*argv[:-1], "-progress", "pipe:1", "-nostats", argv[-1]]
    stderr_lines: list[str] = []

    process = subprocess.Popen(
        progress_argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None and process.stderr is not None

    try:
        with Progress(
            SpinnerColumn(style="ffx.accent"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(complete_style="ffx.accent", finished_style="ffx.ok"),
            TextColumn("[ffx.accent]{task.percentage:>3.0f}%[/ffx.accent]"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                description, total=total_duration if total_duration > 0 else None
            )

            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")

            open_streams = 2
            while open_streams > 0:
                for key, _ in selector.select():
                    line = key.fileobj.readline()
                    if line == "":
                        selector.unregister(key.fileobj)
                        open_streams -= 1
                        continue
                    if key.data == "stdout":
                        _handle_progress_line(line, progress, task, total_duration)
                    else:
                        stderr_lines.append(line)

            returncode = process.wait()
    except KeyboardInterrupt:
        _kill(process)
        raise

    return returncode, stderr_lines


def _kill(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _handle_progress_line(line: str, progress: Progress, task, total_duration: float) -> None:
    line = line.strip()
    if not line or "=" not in line:
        return
    key, _, value = line.partition("=")
    if key == "out_time_ms" and total_duration > 0:
        try:
            seconds = int(value) / 1_000_000
        except ValueError:
            return
        progress.update(task, completed=min(seconds, total_duration))
    elif key == "progress" and value.strip() == "end":
        progress.update(task, completed=total_duration if total_duration > 0 else None)
