from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from rich import box
from rich.panel import Panel
from rich.table import Table

from ffx import hardware, preflight, presets as preset_calc, probe, recipes
from ffx.tui import session as tui_session
from ffx.analyse import run_qc, summary_rows
from ffx.analyse import prompt as analyse_prompt
from ffx.build import build_argv, build_two_pass_argvs, needs_two_pass
from ffx.models import FFmpegJob, MediaInfo, OutputConfig, Recipe
from ffx.operations import CATEGORIES, get_operation
from ffx.runner import FFmpegCancelled, FFmpegRunError, run as run_ffmpeg
from ffx.ui import prompts
from ffx.ui.theme import CATEGORY_COLORS, FIELD_COLORS, console, print_banner, print_step

_MEDIA_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".mxf", ".ts", ".m4v",
    ".mp3", ".wav", ".flac", ".aac", ".m4a",
}


def main() -> None:
    if _use_tui():
        if not preflight.check():
            sys.exit(1)
        caps = hardware.detect()
        from ffx.tui.app import FFXApp

        app = FFXApp(lambda: _flow(caps))
        app.run()
        sys.exit(app.return_code or 0)

    print_banner()
    if not preflight.check():
        sys.exit(1)
    _flow(hardware.detect())


def _use_tui() -> bool:
    # The full-screen app needs a real terminal; under pytest, pipes, or
    # FFX_CLASSIC=1 the original inline wizard runs instead.
    return sys.stdout.isatty() and os.environ.get("FFX_CLASSIC") != "1"


def _flow(caps) -> None:
    try:
        while True:
            inputs = _select_inputs()
            representative = probe.probe(inputs[0])
            _show_input_feedback(inputs, representative)

            ordered_ops = None
            output_dir = suffix = None
            stage = "operations"
            restart = False

            while True:
                if stage == "operations":
                    ordered_ops = _select_operations(representative, caps, ordered_ops)
                    if ordered_ops is None:
                        # Backed all the way out of the (now empty) pipeline
                        # menu - nothing left to back into but a new file.
                        restart = True
                        break
                    stage = "output"
                elif stage == "output":
                    result = _select_output(inputs[0], ordered_ops)
                    if result is None:
                        stage = "operations"
                        continue
                    output_dir, suffix = result
                    stage = "confirm"
                elif stage == "confirm":
                    if _confirm_and_run(inputs, ordered_ops, output_dir, suffix, caps) == "back":
                        stage = "output"
                        continue
                    break

            if not restart:
                break
            console.print("Alright, let's pick a different file.", style="ffx.muted")
    except KeyboardInterrupt:
        console.print("\nAlright, bailing.", style="ffx.muted")
        sys.exit(130)


_CATEGORY_ICON = {
    "convert": "⇄", "cut": "✂", "scale": "⤢", "crop": "▣", "thumbnail": "◫", "orientate": "⟳",
    "colour": "◐", "text": "𝐓", "caption": "¶", "timecode": "◔", "composite": "⧉", "sequence": "⋯",
    "time": "◷", "sound": "♪", "metadata": "▤", "repair": "✚",
}


def _select_inputs() -> list[Path]:
    print_step(1, 4, "Pick your input")
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
    table = Table(title=title, show_header=False, box=box.SQUARE, border_style="ffx.border")
    table.add_column("Property", style="ffx.muted")
    table.add_column("Value")
    for key, value in summary_rows(representative):
        if key == "File":
            continue
        _add_field_row(table, key, value)
    if not tui_session.show_media(table):
        console.print(table)


def _add_field_row(table: Table, key: str, value: str) -> None:
    color = FIELD_COLORS.get(key)
    table.add_row(key, f"[bold {color}]{value}[/]" if color else f"[bold]{value}[/]")


def _select_operations(media, caps, ordered_ops=None):
    print_step(2, 4, "Build your pipeline")

    ordered_ops = list(ordered_ops or [])

    while True:
        if ordered_ops:
            _print_pipeline(ordered_ops, media, caps)
        else:
            tui_session.show_pipeline("[dim]Pipeline is empty.[/dim]")

        # Re-listed every loop (cheap - just a directory glob), so a
        # delete inside the Recipes flow is reflected the next time this
        # menu is shown, rather than sitting stale for the rest of the
        # session.
        saved_recipes = recipes.list_recipes()

        menu = []
        for m in CATEGORIES:
            label = f"{_CATEGORY_ICON.get(m.name, '▸')} {m.display_name} — {m.description}"
            # An operation can declare it won't work on this ffmpeg build
            # (e.g. Text without drawtext) - say so on the menu entry
            # itself instead of letting the pick silently bounce back.
            reason_fn = getattr(m, "unavailable_reason", None)
            reason = reason_fn(caps) if reason_fn else None
            if reason:
                label += f"  [unavailable: {reason}]"
            menu.append((label, m.name))
        menu.append(("◎ Analyse — inspect it, nothing changes", "analyse"))
        if saved_recipes:
            menu.append(("★ Recipes — reuse a saved pipeline", "recipes"))
        if ordered_ops:
            menu.append(("✓ Done — send it", "done"))

        choice = prompts.run_wizard(
            prompts.choose, "What next?", menu, default="done" if ordered_ops else None
        )

        if choice is None:
            # Backed out of this menu itself, not one of its sub-flows -
            # undo the most recently queued operation if there is one,
            # otherwise there's nothing left here to back into.
            if ordered_ops:
                removed, _ = ordered_ops.pop()
                console.print(f"Removed {removed.display_name} from the pipeline.", style="ffx.muted")
                continue
            return None

        if choice == "done":
            break
        if choice == "analyse":
            _run_analyse(media)
            continue
        if choice == "recipes":
            picked = _pick_recipe(saved_recipes)
            if picked is not None:
                ordered_ops = picked
            continue

        module = get_operation(choice)
        params = prompts.run_wizard(module.prompt, media, caps)
        if params is None:
            console.print(f"Cancelled {module.display_name}.", style="ffx.muted")
            continue
        ordered_ops.append((module, params))

    return ordered_ops


def _print_pipeline(ordered_ops, media, caps) -> None:
    lines = []
    for i, (module, params) in enumerate(ordered_ops, 1):
        op = module.build(params, media, caps)
        icon = _CATEGORY_ICON.get(module.name, "▸")
        color = CATEGORY_COLORS.get(module.name, "grey70")
        lines.append(
            f"[ffx.ok]{i}.[/ffx.ok] [bold {color}]{icon} {module.display_name}[/]  {op.description}"
        )
    if tui_session.show_pipeline("\n".join(lines)):
        return
    console.print(
        Panel("\n".join(lines), title="Pipeline", title_align="left", border_style="ffx.border", box=box.SQUARE)
    )


def _run_analyse(media) -> None:
    params = prompts.run_wizard(analyse_prompt)
    if params is None:
        return
    table = Table(title=f"Analysis: {media.path.name}", box=box.SQUARE, border_style="ffx.border")
    table.add_column("Property", style="ffx.muted")
    table.add_column("Value")
    for key, value in summary_rows(media):
        _add_field_row(table, key, value)
    console.print(table)

    if params["checks"]:
        findings = run_qc(media.path, params["checks"], media.duration, console)
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


_DELETE_RECIPES = "__ffx_delete_recipes__"


def _pick_recipe(saved_recipes: list[Recipe]):
    # Selection is by index rather than handing the Recipe object itself
    # to InquirerPy as the Choice value - a dataclass instance round-
    # tripped through select/checkbox has been observed coming back as a
    # plain dict (confirmed directly), the same issue prompts.choose_preset
    # already works around.
    choices = [(f"★ {r.name} — {r.description}", i) for i, r in enumerate(saved_recipes)]
    choices.append(("✕ Delete recipes...", _DELETE_RECIPES))
    choice = prompts.run_wizard(prompts.choose, "Which recipe?", choices)

    if choice == _DELETE_RECIPES:
        _delete_recipes(saved_recipes)
        return None
    if choice is None:
        return None

    recipe = saved_recipes[choice]
    ordered_ops = []
    for entry in recipe.operations:
        module = get_operation(entry["name"])
        ordered_ops.append((module, entry["params"]))
    console.print(f"Loaded {recipe.name} ({len(ordered_ops)} step(s))", style="ffx.ok")
    return ordered_ops


def _delete_recipes(saved_recipes: list[Recipe]) -> None:
    choices = [(f"★ {r.name} — {r.description}", i) for i, r in enumerate(saved_recipes)]
    selected_indexes = prompts.run_wizard(
        prompts.multi_choose,
        "Delete which recipe(s)? (space to toggle, enter to confirm)",
        choices,
    )
    if not selected_indexes:
        console.print("Nothing deleted.", style="ffx.muted")
        return
    to_delete = [saved_recipes[i] for i in selected_indexes]

    names = ", ".join(r.name for r in to_delete)
    confirmed = prompts.run_wizard(
        prompts.ask_confirm, f"Delete {names}? This can't be undone.", default=False
    )
    if not confirmed:
        console.print("Nothing deleted.", style="ffx.muted")
        return

    for recipe in to_delete:
        recipes.delete(recipe.name)
    console.print(f"Deleted {names}.", style="ffx.ok")


def _select_output(first_input: Path, ordered_ops):
    print_step(3, 4, "Pick your output")
    suffix = "-".join(module.name for module, _ in ordered_ops)
    default_dir = str(first_input.parent)
    out_dir = prompts.run_wizard(prompts.ask_output_path, "Output directory:", default=default_dir)
    if out_dir is None:
        return None
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
    # mode, sound.py's extract mode, and repair.py's tolerant remux all
    # emit "-c copy" or "-vn" (no re-encode/no video), which can't be
    # combined with another op that needs a video filter/re-encode.
    has_copy_cut = any(
        module.name == "cut" and not params.get("reencode", True) for module, params in ordered_ops
    )
    has_audio_only_extract = any(
        module.name == "sound" and params.get("mode") == "extract" for module, params in ordered_ops
    )
    has_remux = any(
        module.name == "repair" and params.get("mode") == "remux" for module, params in ordered_ops
    )
    return (has_copy_cut or has_audio_only_extract or has_remux) and len(ordered_ops) > 1


def _filter_drop_conflict(ops) -> tuple[str, list[str]] | None:
    # build_argv uses one op's filter_complex verbatim and ignores every
    # other op's simple -vf/-af fragments (ffmpeg can't mix them on the
    # same stream) - so e.g. Composite queued alongside Scale silently
    # drops the scale. Returns (filter-graph op name, dropped op names)
    # when that's about to happen, so the user hears it from us instead
    # of noticing the output is wrong.
    fc_op = next((op for op in ops if op.filter_complex), None)
    if fc_op is None:
        return None
    dropped = [
        op.display_name for op in ops if not op.filter_complex and (op.video_filter or op.audio_filter)
    ]
    return (fc_op.display_name, dropped) if dropped else None


def _confirm_and_run(inputs, ordered_ops, output_dir, suffix, caps) -> str:
    print_step(4, 4, "Do this?")
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

    conflict = _filter_drop_conflict(jobs[0][2].operations)
    if conflict is not None:
        fc_name, dropped = conflict
        console.print(
            f"Heads up: {fc_name} builds its own filter graph, so "
            f"{', '.join(dropped)} won't be applied in the same run — "
            "do that as a separate pass on the result instead.",
            style="ffx.warn",
        )

    command_lines = "\n".join(
        f"[ffx.command]{' '.join(argv)}[/ffx.command]"
        + ("  [ffx.muted](runs as a 2-pass encode)[/ffx.muted]" if needs_two_pass(job) else "")
        for _, _, job, argv in jobs
    )
    console.print()
    console.print(
        Panel(
            command_lines,
            title=f"Command{'s' if len(jobs) > 1 else ''} to run",
            title_align="left",
            border_style="ffx.ok",
            box=box.SQUARE,
        )
    )

    run_choice = prompts.run_wizard(
        prompts.ask_confirm,
        "Run it?" if len(jobs) == 1 else f"Run all {len(jobs)}?",
        default=True,
        hint="No declines outright.",
    )
    if run_choice is None:
        return "back"
    if not run_choice:
        console.print("Fair enough, holding off.", style="ffx.muted")
        return "done"

    for input_path, media, job, argv in jobs:
        console.print(f"\n[bold]▸ Cooking[/bold] {input_path.name}  [ffx.muted](Ctrl+C to cancel)[/ffx.muted]")
        try:
            if needs_two_pass(job):
                with tempfile.TemporaryDirectory(prefix="ffx-2pass-") as tmpdir:
                    passlog_base = os.path.join(tmpdir, "pass")
                    pass1_argv, pass2_argv = build_two_pass_argvs(job, passlog_base)
                    run_ffmpeg(
                        pass1_argv,
                        total_duration=media.duration,
                        console=console,
                        description="Pass 1/2 — analyzing",
                        cleanup_on_cancel=False,
                    )
                    run_ffmpeg(
                        pass2_argv,
                        total_duration=media.duration,
                        console=console,
                        description="Pass 2/2 — encoding",
                    )
            else:
                run_ffmpeg(argv, total_duration=media.duration, console=console)
        except FFmpegCancelled:
            console.print("Alright, backing off — cleaned up after myself.", style="ffx.warn")
            return "done"
        except FFmpegRunError as exc:
            console.print(f"Well, that didn't work. ffmpeg says (exit {exc.returncode}):", style="ffx.error")
            console.print(exc.stderr_tail, style="ffx.muted")
            sys.exit(exc.returncode)
        console.print(f"Done. {job.output.path} is ready to go.", style="ffx.ok")
        _print_size_change(input_path, job.output.path)

    if prompts.ask_confirm("Worth saving as a recipe for next time?", default=False):
        _save_recipe(ordered_ops, jobs[0][2].operations)
    return "done"


_BAR_WIDTH = 24


def _bar(value: float, largest: float) -> str:
    filled = max(1, round((value / largest) * _BAR_WIDTH)) if value > 0 else 0
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


def _print_size_change(input_path: Path, output_path: Path) -> None:
    try:
        before = input_path.stat().st_size
        after = output_path.stat().st_size
    except OSError:
        return
    if before <= 0:
        return

    pct = (1 - after / before) * 100
    if pct >= 0.5:
        change, style = f"{pct:.0f}% smaller", "ffx.ok"
    elif pct <= -0.5:
        change, style = f"{-pct:.0f}% larger", "ffx.warn"
    else:
        change, style = "about the same size", "ffx.muted"

    largest = max(before, after, 1)
    before_bar = _bar(before, largest)
    after_bar = _bar(after, largest)
    before_size = preset_calc.humanize_size(before / 1024 / 1024)
    after_size = preset_calc.humanize_size(after / 1024 / 1024)

    console.print(f"  Before  [ffx.muted]{before_bar}[/ffx.muted]  {before_size}")
    console.print(f"  After   [{style}]{after_bar}[/{style}]  {after_size}   [{style}]{change}[/{style}]")


def _save_recipe(ordered_ops, operations) -> None:
    recipe_name = prompts.ask_text("Recipe name:")
    # Generated straight from what each op actually does (the same
    # description shown in the Pipeline panel and command review), not a
    # free-text description someone has to write - precise and consistent
    # across recipes instead of a human paraphrase that drifts over time.
    recipe_description = " → ".join(op.description for op in operations)
    recipe = Recipe(
        name=recipe_name,
        description=recipe_description,
        operations=[{"name": module.name, "params": params} for module, params in ordered_ops],
    )
    path = recipes.save(recipe)
    console.print(f"Saved. That's one click next time: {path}", style="ffx.ok")


if __name__ == "__main__":
    main()
