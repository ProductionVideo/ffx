from __future__ import annotations

import sys
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from ffx import hardware, probe, recipes
from ffx.analyse import run_qc, summary_rows
from ffx.analyse import prompt as analyse_prompt
from ffx.build import build_argv
from ffx.models import FFmpegJob, MediaInfo, OutputConfig, Recipe
from ffx.operations import CATEGORIES, get_operation
from ffx.runner import FFmpegCancelled, FFmpegRunError, run as run_ffmpeg
from ffx.ui import prompts
from ffx.ui.theme import console, print_banner, print_step

_MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".mxf", ".ts", ".m4v",
    ".mp3", ".wav", ".flac", ".aac", ".m4a",
}


def main() -> None:
    print_banner()
    caps = hardware.detect()

    try:
        inputs = _select_inputs()
        representative = probe.probe(inputs[0])
        _show_input_feedback(inputs, representative)

        ordered_ops = _select_operations(representative, caps)
        if ordered_ops is None:
            console.print("Nothing queued, nothing to do. Come back when you're ready.", style="ffx.muted")
            return

        output_dir, suffix = _select_output(inputs[0], ordered_ops)

        _confirm_and_run(inputs, ordered_ops, output_dir, suffix, caps)
    except KeyboardInterrupt:
        console.print("\nAlright, bailing.", style="ffx.muted")
        sys.exit(130)


_CATEGORY_ICON = {"convert": "⇄", "cut": "✂", "scale": "⤢", "crop": "▣", "time": "◷", "sound": "♪"}


def _select_inputs() -> list[Path]:
    print_step(1, 5, "Where — pick your input")
    path = prompts.ask_existing_path("Path to a media file or directory:")
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() in _MEDIA_EXTENSIONS)
        if not files:
            console.print(f"No media files found in {path}", style="ffx.error")
            sys.exit(1)
        console.print(f"Found {len(files)} file(s) in {path}", style="ffx.ok")
        return files
    return [path]


def _show_input_feedback(inputs: list[Path], representative: MediaInfo) -> None:
    """Confirm what we're actually working with as soon as it's picked -
    resolution/codec/duration/size, so a wrong file is obvious immediately
    rather than after building a whole command around it.
    """
    title = representative.path.name if len(inputs) == 1 else f"{representative.path.name} (+ {len(inputs) - 1} more)"
    table = Table(title=title, show_header=False)
    table.add_column("Property", style="ffx.muted")
    table.add_column("Value")
    for key, value in summary_rows(representative):
        if key == "File":
            continue
        table.add_row(key, value)
    console.print(table)


def _select_operations(media, caps):
    print_step(2, 5, "What — build your pipeline")

    ordered_ops: list[tuple[object, dict]] = []
    saved_recipes = recipes.list_recipes()

    while True:
        if ordered_ops:
            _print_pipeline(ordered_ops, media, caps)

        menu = [
            (f"{_CATEGORY_ICON.get(m.name, '▸')} {m.display_name} — {m.description}", m.name)
            for m in CATEGORIES
        ]
        menu.append(("◎ Analyse — inspect it, nothing changes", "analyse"))
        if saved_recipes:
            menu.append(("★ Recipes — reuse a saved pipeline", "recipes"))
        if ordered_ops:
            menu.append(("✓ Done — send it", "done"))

        choice = prompts.choose("What next?", menu)

        if choice == "done":
            break
        if choice == "analyse":
            _run_analyse(media)
            continue
        if choice == "recipes":
            ordered_ops = _pick_recipe(saved_recipes)
            continue

        module = get_operation(choice)
        params = module.prompt(media, caps)
        ordered_ops.append((module, params))

    return ordered_ops or None


def _print_pipeline(ordered_ops, media, caps) -> None:
    lines = []
    for i, (module, params) in enumerate(ordered_ops, 1):
        op = module.build(params, media, caps)
        icon = _CATEGORY_ICON.get(module.name, "▸")
        lines.append(f"[ffx.ok]{i}.[/ffx.ok] {icon} [bold]{module.display_name}[/bold]  {op.description}")
    console.print(Panel("\n".join(lines), title="Pipeline", title_align="left", border_style="ffx.ok"))


def _run_analyse(media) -> None:
    params = analyse_prompt()
    table = Table(title=f"Analysis: {media.path.name}")
    table.add_column("Property")
    table.add_column("Value")
    for key, value in summary_rows(media):
        table.add_row(key, value)
    console.print(table)

    if params["checks"]:
        findings = run_qc(media.path, params["checks"])
        if "black" in params["checks"]:
            _print_findings("Black sections", findings.black_sections, "start={0:.2f}s end={1:.2f}s dur={2:.2f}s")
        if "silence" in params["checks"]:
            _print_findings("Silent sections", findings.silence_sections, "start={0:.2f}s end={1} dur={2}")
        if "freeze" in params["checks"]:
            for s in findings.freeze_starts:
                console.print(f"  Frozen section starting at {s:.2f}s")
            if not findings.freeze_starts:
                console.print("  No frozen sections detected", style="ffx.muted")


def _print_findings(title: str, sections: list, fmt: str) -> None:
    console.print(f"[bold]{title}:[/bold]")
    if not sections:
        console.print("  None detected", style="ffx.muted")
        return
    for section in sections:
        console.print("  " + fmt.format(*section))


def _pick_recipe(saved_recipes: list[Recipe]) -> list[tuple[object, dict]]:
    recipe = prompts.choose(
        "Which recipe?",
        [(f"★ {r.name} — {r.description}", r) for r in saved_recipes],
    )
    ordered_ops = []
    for entry in recipe.operations:
        module = get_operation(entry["name"])
        ordered_ops.append((module, entry["params"]))
    console.print(f"Loaded {recipe.name} ({len(ordered_ops)} step(s))", style="ffx.ok")
    return ordered_ops


def _select_output(first_input: Path, ordered_ops) -> tuple[Path, str]:
    print_step(4, 5, "Where — pick your output")
    suffix = "-".join(module.name for module, _ in ordered_ops)
    default_dir = str(first_input.parent)
    out_dir = prompts.ask_output_path("Output directory:", default=default_dir)
    return out_dir, suffix


def _output_extension(ordered_ops, source_ext: str) -> str:
    # Any op can override the output container (Convert always does;
    # Sound does when extracting audio-only) by exposing an
    # output_extension(params) -> str | None; later ops win.
    for module, params in reversed(ordered_ops):
        ext_fn = getattr(module, "output_extension", None)
        if ext_fn:
            ext = ext_fn(params)
            if ext:
                return "." + ext.lstrip(".")
    return source_ext


def _has_stream_copy_conflict(ordered_ops) -> bool:
    # Cheap heuristics for the pre-flight warning below: cut.py's fast
    # mode ("-c copy") and sound.py's extract mode ("-vn", no video
    # stream) each can't be combined with another op that needs a
    # video filter/re-encode.
    has_copy_cut = any(
        module.name == "cut" and not params.get("reencode", True) for module, params in ordered_ops
    )
    has_audio_only_extract = any(
        module.name == "sound" and params.get("mode") == "extract" for module, params in ordered_ops
    )
    return (has_copy_cut or has_audio_only_extract) and len(ordered_ops) > 1


def _confirm_and_run(inputs, ordered_ops, output_dir, suffix, caps) -> None:
    print_step(5, 5, "Go — review, then send it")
    output_dir.mkdir(parents=True, exist_ok=True)

    if _has_stream_copy_conflict(ordered_ops):
        console.print(
            "Heads up: a no-re-encode cut or an audio-only extract combined with another "
            "video-affecting operation will likely conflict in ffmpeg.",
            style="ffx.warn",
        )

    jobs = []
    for input_path in inputs:
        media = probe.probe(input_path)
        ops = [module.build(params, media, caps) for module, params in ordered_ops]
        ext = _output_extension(ordered_ops, input_path.suffix)
        out_name = f"{input_path.stem}.{suffix}{ext}" if suffix else f"{input_path.stem}.out{ext}"
        job = FFmpegJob(
            inputs=[input_path],
            operations=ops,
            output=OutputConfig(path=output_dir / out_name),
            hardware=caps,
        )
        argv = build_argv(job)
        jobs.append((input_path, media, job, argv))

    command_lines = "\n".join(f"[ffx.command]{' '.join(argv)}[/ffx.command]" for _, _, _, argv in jobs)
    console.print()
    console.print(
        Panel(
            command_lines,
            title=f"Command{'s' if len(jobs) > 1 else ''} to run",
            title_align="left",
            border_style="ffx.step",
        )
    )

    if not prompts.ask_confirm(
        "Run it?" if len(jobs) == 1 else f"Run all {len(jobs)}?",
        default=True,
        hint="Last chance to back out.",
    ):
        console.print("Fair enough, holding off.", style="ffx.muted")
        return

    for input_path, media, job, argv in jobs:
        console.print(f"\n[ffx.step]Cooking[/ffx.step] {input_path.name}  [ffx.muted](Ctrl+C to cancel)[/ffx.muted]")
        try:
            run_ffmpeg(argv, total_duration=media.duration, console=console)
        except FFmpegCancelled:
            console.print("Alright, backing off — cleaned up after myself.", style="ffx.warn")
            return
        except FFmpegRunError as exc:
            console.print(f"Well, that didn't work. ffmpeg says (exit {exc.returncode}):", style="ffx.error")
            console.print(exc.stderr_tail, style="ffx.muted")
            sys.exit(exc.returncode)
        console.print(f"Done. {job.output.path} is ready to go.", style="ffx.ok")

    if prompts.ask_confirm("Worth saving as a recipe for next time?", default=False):
        _save_recipe(ordered_ops)


def _save_recipe(ordered_ops) -> None:
    recipe_name = prompts.ask_text("Recipe name:")
    recipe_description = prompts.ask_text("Short description:")
    recipe = Recipe(
        name=recipe_name,
        description=recipe_description,
        operations=[{"name": module.name, "params": params} for module, params in ordered_ops],
    )
    path = recipes.save(recipe)
    console.print(f"Saved. That's one click next time: {path}", style="ffx.ok")


if __name__ == "__main__":
    main()
