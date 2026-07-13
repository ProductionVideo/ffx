#!/bin/sh
# ffx installer — sets up everything ffx needs:
#   * uv        (installed if missing; brings its own Python, no system Python needed)
#   * ffx       (installed/updated as a uv tool, with textual/rich/InquirerPy)
#   * ffmpeg    (offered via Homebrew if missing; ffx also re-checks at launch)
#
# Usage:
#   curl -LsSf https://raw.githubusercontent.com/GITHUB_USER/ffx/main/install.sh | sh
set -eu

REPO_URL="https://github.com/GITHUB_USER/ffx"

say()  { printf '\033[1;36mffx installer:\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33mffx installer:\033[0m %s\n' "$1"; }
fail() { printf '\033[1;31mffx installer:\033[0m %s\n' "$1" >&2; exit 1; }

# Reads y/n even when the script body arrives on stdin (curl | sh).
confirm() {
    printf '%s [Y/n] ' "$1"
    if [ -r /dev/tty ]; then
        read -r answer < /dev/tty || answer=""
    else
        answer=""
        printf '(no terminal - assuming yes)\n'
    fi
    case "$answer" in
        [Nn]*) return 1 ;;
        *) return 0 ;;
    esac
}

# --- uv (brings its own Python) ---------------------------------------------
if command -v uv >/dev/null 2>&1; then
    say "uv is already installed."
else
    say "Installing uv (Python toolchain manager - it downloads Python itself)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # The uv installer puts it in ~/.local/bin; make it visible to the rest
    # of this script even though the current shell profile hasn't reloaded.
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null 2>&1 || fail "uv didn't install cleanly - see https://docs.astral.sh/uv/"
fi

# --- ffx ---------------------------------------------------------------------
say "Installing ffx..."
uv tool install --force --from "git+${REPO_URL}" ffx
say "ffx installed."

# uv places tools in ~/.local/bin; wire up PATH for future shells if needed.
if ! command -v ffx >/dev/null 2>&1; then
    uv tool update-shell || true
    export PATH="$HOME/.local/bin:$PATH"
    command -v ffx >/dev/null 2>&1 || warn "Open a new terminal (or add ~/.local/bin to PATH) to use 'ffx'."
fi

# --- ffmpeg ------------------------------------------------------------------
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
    say "ffmpeg is already installed."
    if ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q drawtext; then
        warn "This ffmpeg build lacks the drawtext filter, so ffx's Text overlay"
        warn "operation will be unavailable. 'brew install ffmpeg-full' includes it."
    fi
elif command -v brew >/dev/null 2>&1; then
    if confirm "ffmpeg isn't installed. Install it with Homebrew now?"; then
        brew install ffmpeg
    else
        warn "Skipped - ffx will offer to install ffmpeg when you first run it."
    fi
else
    warn "ffmpeg isn't installed and Homebrew wasn't found."
    warn "Install Homebrew (https://brew.sh) then run: brew install ffmpeg"
    warn "ffx will also walk you through this when you first run it."
fi

say "Done. Run 'ffx' to get started."
