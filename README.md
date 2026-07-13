# ffx

**ffmpeg, for the simple.**

ffx is an interactive frontend for ffmpeg. Instead of assembling flags from Stack Overflow, you answer a few questions — pick a file, build a pipeline of operations, confirm — and ffx builds and runs the ffmpeg command for you, with a live progress bar. It always shows you the exact command before running it, so it doubles as a way to *learn* ffmpeg rather than hide it.

## What it can do

Operations compose into a pipeline — queue several against one file, or against every media file in a directory:

| Operation | What it does |
|---|---|
| **Convert** | Swap codec/container: H.264, HEVC, AV1, VP9, ProRes, DNxHR, MPEG-2, or stream copy. Quality tiers with estimated output sizes, exact target-size mode, optional 2-pass |
| **Cut** | Trim to a time range, re-encoded or instant stream copy |
| **Scale** | Resize by width, height, percentage, or preset |
| **Crop** | Manual crop or auto-detect black bars (`cropdetect`) |
| **Orientate** | Rotate / flip |
| **Colour** | Brightness, contrast, saturation, temperature |
| **Text** | Burn in text overlays (`drawtext`) |
| **Composite** | Watermark, stack, side-by-side, chroma key |
| **Time** | Speed up, slow down, reverse |
| **Sound** | Adjust volume, normalize, strip or extract audio |
| **Metadata** | View / edit container tags |
| **Repair** | Tolerant remux for broken files |
| **Analyse** | Inspect a file; QC scans for black frames, silence, and freezes |

Plus:

- **Recipes** — save a pipeline you liked and replay it in one pick next time.
- **Hardware awareness** — detects VideoToolbox on Apple Silicon and offers hardware encoding where it exists; detects which filters your ffmpeg build actually has before offering them.
- **Batch mode** — point it at a directory and the pipeline runs across every media file.
- **Back navigation everywhere** — every question supports going back (Ctrl+Z, or the Back item in menus) without losing the answers you already gave.
- **Honest previews** — the full command is shown before anything runs; size estimates on quality choices; before/after size comparison when it's done.

## Install

One command — it sets up everything ffx needs (uv with its own Python, ffx itself, and offers to install ffmpeg via Homebrew if it's missing):

```sh
curl -LsSf https://raw.githubusercontent.com/ProductionVideo/ffx/main/install.sh | sh
```

ffx also re-checks for ffmpeg every launch and walks you through installing it if it's gone.

<details>
<summary>Manual install</summary>

Requires Python 3.11+ and ffmpeg.

```sh
uv tool install --from git+https://github.com/ProductionVideo/ffx ffx
```

Or from a clone, for development:

```sh
git clone https://github.com/ProductionVideo/ffx && cd ffx
uv sync
uv run ffx
```
</details>

> **Platform note:** ffx is developed macOS-first. Everything works on Linux, but hardware encoding (VideoToolbox) and the Homebrew install offer are macOS-only.

## Usage

Run `ffx` and follow the four steps:

1. **Pick your input** — a file, or a directory for batch mode. Paths pasted from Finder (quoted or backslash-escaped) are handled.
2. **Build your pipeline** — add operations one at a time; each shows what it will do as you queue it. Or load a saved recipe.
3. **Pick your output** — output directory; filenames are derived from the input plus the operations applied.
4. **Confirm** — review the exact ffmpeg command(s), then run with live progress. Ctrl+C cancels cleanly and removes the partial file.

## Development

```sh
uv sync
uv run pytest
```

The test suite (100+ tests, sub-second) covers argv construction, every operation, and the wizard flow without invoking ffmpeg, plus a smoke test that drives the whole app end-to-end against a real ffmpeg.

## Interfaces

Run in a terminal, ffx opens a full-screen app (built on [Textual](https://textual.textualize.io/)) with always-visible media info and pipeline panes, an activity log, and in-place encode progress — in the spirit of btop/lazygit. Set `FFX_CLASSIC=1` to use the original inline wizard instead; both drive the same operations, and every prompt supports going back (Esc in the app, Ctrl+Z inline).

## Roadmap

- Redesign operation flows as single-screen forms (Convert's six questions on one screen) instead of sequential prompts.
- A file browser pane for input picking.
- Batch progress overview when running a directory.
