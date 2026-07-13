from __future__ import annotations

import shutil
import subprocess

from ffx.ui import prompts
from ffx.ui.theme import console

_REQUIRED = ("ffmpeg", "ffprobe")


def check() -> bool:
    """Verify ffmpeg/ffprobe are on PATH before doing anything else.

    Silent when everything's already there - the common case shouldn't
    print anything. On failure, explains what's missing and, if Homebrew
    is available, offers to install it right now rather than leaving the
    user to hunt down a cryptic "ffmpeg: command not found" (or worse, a
    raw traceback from deep inside a subprocess call) after they've
    already picked a file and built a whole pipeline.
    """
    missing = [name for name in _REQUIRED if shutil.which(name) is None]
    if not missing:
        return True

    console.print()
    console.print(
        f"ffx needs {' and '.join(missing)} installed, but couldn't find "
        f"{'it' if len(missing) == 1 else 'them'} on your PATH.",
        style="ffx.error",
    )

    brew = shutil.which("brew")
    if brew is None:
        console.print(
            "Install Homebrew first (https://brew.sh), then run:\n  brew install ffmpeg",
            style="ffx.muted",
        )
        return False

    if not prompts.ask_confirm("Install ffmpeg with Homebrew now?", default=True):
        console.print("Okay - install it yourself with: brew install ffmpeg", style="ffx.muted")
        return False

    console.print("Running: brew install ffmpeg ...", style="ffx.muted")
    result = subprocess.run([brew, "install", "ffmpeg"])
    if result.returncode != 0 or shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        console.print(
            "That didn't finish cleanly - try running it yourself: brew install ffmpeg",
            style="ffx.error",
        )
        return False

    console.print("ffmpeg installed.", style="ffx.ok")
    return True
