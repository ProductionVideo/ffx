from __future__ import annotations

import os

from ffx.models import FFmpegJob


def build_argv(job: FFmpegJob) -> list[str]:
    """Fold an ordered list of OperationSettings into one ffmpeg argv.

    Rules (see the plan's "operation composition model"):
    - args_before_input from every op, in order, go before the -i flags.
    - Every op's extra_inputs (a watermark image, a second video to
      stack/overlay against) get their own -i flags after the job's main
      input(s), each preceded by that input's own extra_input_args (e.g.
      -loop 1 for a still image). The op supplying filter_complex.
    - If any op sets filter_complex, that op's fragment is used verbatim
      (with its "{in0}", "{in1}", ... placeholders resolved to the real
      ffmpeg input index of its own extra_inputs) and all other ops'
      simple video_filter/audio_filter fragments are ignored (ffmpeg can't
      mix -vf/-af with -filter_complex on the same stream). Only one op is
      expected to need filter_complex at a time; later phases that
      legitimately combine multiple filter_complex ops will need to merge
      fragments here instead.
    - Otherwise, video_filter fragments are joined with "," into one -vf,
      and audio_filter fragments joined into one -af.
    - output_args are concatenated in order; later ops can override an
      earlier op's flag (e.g. a later codec choice wins) since ffmpeg
      itself takes the last occurrence of a repeated output option.
    """
    argv: list[str] = ["ffmpeg", "-y"]

    for op in job.operations:
        argv.extend(op.args_before_input)

    for input_path in job.inputs:
        argv.extend(["-i", str(input_path)])

    next_index = len(job.inputs)
    extra_indices: dict[int, list[int]] = {}
    for i, op in enumerate(job.operations):
        if not op.extra_inputs:
            continue
        indices = []
        for j, path in enumerate(op.extra_inputs):
            if j < len(op.extra_input_args):
                argv.extend(op.extra_input_args[j])
            argv.extend(["-i", str(path)])
            indices.append(next_index)
            next_index += 1
        extra_indices[i] = indices

    filter_complex_i = next((i for i, op in enumerate(job.operations) if op.filter_complex), None)

    if filter_complex_i is not None:
        fc = job.operations[filter_complex_i].filter_complex
        for slot, idx in enumerate(extra_indices.get(filter_complex_i, [])):
            fc = fc.replace(f"{{in{slot}}}", str(idx))
        argv.extend(["-filter_complex", fc])
    else:
        vf_parts = [part for op in job.operations for part in op.video_filter]
        af_parts = [part for op in job.operations for part in op.audio_filter]
        if vf_parts:
            argv.extend(["-vf", ",".join(vf_parts)])
        if af_parts:
            argv.extend(["-af", ",".join(af_parts)])

    for op in job.operations:
        argv.extend(op.output_args)
        argv.extend(op.non_video_output_args)

    argv.append(str(job.output.path))
    return argv


def needs_two_pass(job: FFmpegJob) -> bool:
    """Whether this job should run as a real analysis-then-encode pair.

    Guarded off if any operation needs filter_complex - the pass-1 builder
    below only reasons about the simple video_filter chain, so a job that
    needs a filter graph falls back to single-pass rather than risk an
    incorrect analysis pass.
    """
    if any(op.filter_complex for op in job.operations):
        return False
    return any(op.two_pass for op in job.operations)


def build_two_pass_argvs(job: FFmpegJob, passlog_base: str) -> tuple[list[str], list[str]]:
    """Build the (pass 1, pass 2) argv pair for a 2-pass encode.

    Pass 2 is the normal single-command argv with -pass 2/-passlogfile
    inserted before the output path - the "real" encode, identical to
    what a single-pass job would run.

    Pass 1 re-derives the input/filter side identically, so the analysis
    sees the exact same trimmed/filtered frames pass 2 will encode, but
    keeps only each op's `output_args` (video codec, bitrate, trim
    points) - not `non_video_output_args`, where audio/metadata/mux flags
    live - and discards the result to /dev/null with -an, since only the
    video stream's stats matter for rate control.
    """
    pass2 = build_argv(job)
    output_path = pass2[-1]
    pass2 = pass2[:-1] + ["-pass", "2", "-passlogfile", passlog_base, output_path]

    argv: list[str] = ["ffmpeg", "-y"]
    for op in job.operations:
        argv.extend(op.args_before_input)
    for input_path in job.inputs:
        argv.extend(["-i", str(input_path)])
    vf_parts = [part for op in job.operations for part in op.video_filter]
    if vf_parts:
        argv.extend(["-vf", ",".join(vf_parts)])
    for op in job.operations:
        argv.extend(op.output_args)
    argv += ["-an", "-pass", "1", "-passlogfile", passlog_base, "-f", "null", os.devnull]
    return argv, pass2
