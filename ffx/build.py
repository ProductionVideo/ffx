from __future__ import annotations

from ffx.models import FFmpegJob


def build_argv(job: FFmpegJob) -> list[str]:
    """Fold an ordered list of OperationSettings into one ffmpeg argv.

    Rules (see the plan's "operation composition model"):
    - args_before_input from every op, in order, go before the -i flags.
    - If any op sets filter_complex, that op's fragment is used verbatim
      and all other ops' simple video_filter/audio_filter fragments are
      ignored (ffmpeg can't mix -vf/-af with -filter_complex on the same
      stream). Only one op is expected to need filter_complex at a time
      in Phase 1; later phases that legitimately combine multiple
      filter_complex ops will need to merge fragments here instead.
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

    filter_complex_op = next((op for op in job.operations if op.filter_complex), None)

    if filter_complex_op is not None:
        argv.extend(["-filter_complex", filter_complex_op.filter_complex])
    else:
        vf_parts = [part for op in job.operations for part in op.video_filter]
        af_parts = [part for op in job.operations for part in op.audio_filter]
        if vf_parts:
            argv.extend(["-vf", ",".join(vf_parts)])
        if af_parts:
            argv.extend(["-af", ",".join(af_parts)])

    for op in job.operations:
        argv.extend(op.output_args)

    argv.append(str(job.output.path))
    return argv
