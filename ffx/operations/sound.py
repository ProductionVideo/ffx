from __future__ import annotations

from pathlib import Path

from ffx.models import HardwareCapabilities, MediaInfo, OperationSettings, Preset
from ffx.ui import prompts

name = "sound"
display_name = "Sound"
description = "Extract, mute, remix, or normalize audio"

_AUDIO_CODECS = {
    "aac": {"encoder": "aac", "bitrate_k": 192, "ext": "m4a"},
    "mp3": {"encoder": "libmp3lame", "bitrate_k": 192, "ext": "mp3"},
    "opus": {"encoder": "libopus", "bitrate_k": 128, "ext": "opus"},
    "flac": {"encoder": "flac", "bitrate_k": None, "ext": "flac"},
    "wav": {"encoder": "pcm_s16le", "bitrate_k": None, "ext": "wav"},
}

_SAMPLE_RATES = [("44.1 kHz", "44100"), ("48 kHz", "48000"), ("96 kHz", "96000")]

_BIT_DEPTHS = {"16": "pcm_s16le", "24": "pcm_s24le", "32": "pcm_s32le"}

PRESETS = [
    Preset("Extract to MP3", "Drop the video, keep MP3 audio", {"mode": "extract", "codec": "mp3"}),
    Preset("Remove audio (mute)", "Keep the video, drop the audio track", {"mode": "mute"}),
    Preset(
        "Normalize for streaming (-14 LUFS)",
        "Loudness-normalize to a common streaming target",
        {"mode": "volume", "method": "loudnorm", "target": -14},
    ),
    Preset("Fade out (3s)", "Fade audio out over the last 3 seconds", {"mode": "fade", "fade_in": 0, "fade_out": 3}),
]


def prompt(media: MediaInfo, hardware: HardwareCapabilities) -> dict:
    preset = prompts.choose_preset(PRESETS, message="Sound — choose a preset:")
    if preset is not None:
        return dict(preset.values)

    mode = prompts.choose(
        "What do you want to do with the audio?",
        [
            ("Extract audio (drop the video)", "extract"),
            ("Remove audio (mute)", "mute"),
            ("Replace the audio with another file", "replace"),
            ("Mix in another audio file (music bed, VO)", "mix"),
            ("Channels — mono/stereo/swap/select", "channels"),
            ("Volume, normalize, compress, or limit", "volume"),
            ("Fade in/out", "fade"),
            ("Change sample rate", "resample"),
            ("Change bit depth (PCM)", "bitdepth"),
            ("Delay/advance audio timing", "delay"),
            ("Keep only one audio track", "tracks"),
        ],
    )

    if mode == "extract":
        codec = prompts.choose(
            "Audio format:",
            [("MP3", "mp3"), ("AAC/M4A", "aac"), ("Opus", "opus"), ("FLAC (lossless)", "flac"), ("WAV (uncompressed)", "wav")],
            default="mp3",
        )
        return {"mode": "extract", "codec": codec}

    if mode == "mute":
        return {"mode": "mute"}

    if mode == "replace":
        path = prompts.ask_existing_path("Path to the new audio file:")
        codec = prompts.choose(
            "Audio codec for the result:",
            [("AAC — safe everywhere", "aac"), ("Copy the file's codec as-is", "copy")],
            default="aac",
        )
        return {"mode": "replace", "path": str(path), "codec": codec}

    if mode == "mix":
        path = prompts.ask_existing_path("Path to the audio to mix in:")
        level = prompts.ask_float(
            "Mixed-in volume (0-1):",
            default=0.4,
            min_allowed=0.05,
            max_allowed=1.0,
            hint="How loud the added track sits under the original audio.",
        )
        return {"mode": "mix", "path": str(path), "level": level}

    if mode == "channels":
        action = prompts.choose(
            "Channel action:",
            [
                ("Downmix to mono", "downmix"),
                ("Upmix mono to stereo", "upmix"),
                ("Swap left/right", "swap"),
                ("Left channel only", "left"),
                ("Right channel only", "right"),
            ],
        )
        return {"mode": "channels", "action": action}

    if mode == "volume":
        method = prompts.choose(
            "How?",
            [
                ("Loudness normalize (streaming, -14 LUFS)", "loudnorm_streaming"),
                ("Loudness normalize (broadcast, -23 LUFS)", "loudnorm_broadcast"),
                ("Manual gain (dB)", "gain"),
                ("Compressor (even out dynamics)", "compress"),
                ("Limiter (prevent clipping)", "limit"),
            ],
            default="loudnorm_streaming",
        )
        if method == "gain":
            gain = prompts.ask_float("Gain (dB, negative to lower):", default=0.0)
            return {"mode": "volume", "method": "gain", "gain_db": gain}
        if method in ("compress", "limit"):
            return {"mode": "volume", "method": method}
        target = -14 if method == "loudnorm_streaming" else -23
        return {"mode": "volume", "method": "loudnorm", "target": target}

    if mode == "fade":
        fade_in = prompts.ask_float("Fade in duration (seconds, 0 = none):", default=0.0, min_allowed=0)
        fade_out = prompts.ask_float("Fade out duration (seconds, 0 = none):", default=3.0, min_allowed=0)
        return {"mode": "fade", "fade_in": fade_in, "fade_out": fade_out}

    if mode == "resample":
        rate = prompts.choose("Target sample rate:", _SAMPLE_RATES, default="48000")
        return {"mode": "resample", "rate": rate}

    if mode == "bitdepth":
        depth = prompts.choose(
            "Bit depth:", [("16-bit", "16"), ("24-bit", "24"), ("32-bit float", "32")], default="24"
        )
        return {"mode": "bitdepth", "depth": depth}

    if mode == "delay":
        delay_ms = prompts.ask_float(
            "Delay in milliseconds (negative = audio earlier):",
            default=0.0,
            hint="Shifts audio relative to video - useful for fixing sync drift.",
        )
        return {"mode": "delay", "delay_ms": delay_ms}

    streams = media.audio_streams
    if len(streams) < 2:
        return {"mode": "tracks", "keep_index": 0}
    choices = []
    for i, s in enumerate(streams):
        lang = s.tags.get("language", "")
        label = f"Track {i}: {s.codec_name}, {s.channels or '?'}ch" + (f" [{lang}]" if lang else "")
        choices.append((label, i))
    keep = prompts.choose("Keep which audio track? (others are dropped)", choices)
    return {"mode": "tracks", "keep_index": keep}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    mode = params["mode"]
    if mode == "extract":
        return _build_extract(params)
    if mode == "mute":
        return OperationSettings(
            name=name, display_name=display_name, description="Mute (remove audio)",
            non_video_output_args=["-an"], serializable={},
        )
    if mode == "channels":
        return _build_channels(params)
    if mode == "volume":
        return _build_volume(params)
    if mode == "fade":
        return _build_fade(params, media)
    if mode == "resample":
        return OperationSettings(
            name=name, display_name=display_name, description=f"Resample to {params['rate']}Hz",
            non_video_output_args=["-ar", params["rate"]], serializable={},
        )
    if mode == "bitdepth":
        depth = params["depth"]
        return OperationSettings(
            name=name, display_name=display_name, description=f"{depth}-bit PCM",
            non_video_output_args=["-c:a", _BIT_DEPTHS[depth]], serializable={},
        )
    if mode == "delay":
        return _build_delay(params)
    if mode == "tracks":
        return _build_tracks(params, media)
    if mode == "replace":
        return _build_replace(params)
    if mode == "mix":
        return _build_mix(params)
    raise ValueError(f"unknown sound mode: {mode}")


def _build_replace(params: dict) -> OperationSettings:
    path = Path(params["path"])
    # Everything lives in non_video_output_args: the maps are pure
    # audio/mux concerns, and a 2-pass encode's video-only analysis pass
    # must not see "-map {in0}:a" (its extra input isn't added there).
    args = ["-map", "0:v?", "-map", "{in0}:a", "-shortest"]
    if params.get("codec") == "copy":
        args += ["-c:a", "copy"]
    else:
        args += ["-c:a", "aac", "-b:a", "192k"]
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Replace audio with {path.name}",
        extra_inputs=[path],
        extra_input_args=[[]],
        non_video_output_args=args,
        serializable={},
    )


def _build_mix(params: dict) -> OperationSettings:
    path = Path(params["path"])
    level = params.get("level", 0.4)
    # duration=first: the video keeps its own length; a longer music bed
    # is trimmed, a shorter one just ends (dropout_transition smooths it).
    fc = (
        f"[{{in0}}:a]volume={level}[mixin];"
        "[0:a][mixin]amix=inputs=2:duration=first:dropout_transition=2[outa]"
    )
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Mix in {path.name} at {level:.0%}",
        extra_inputs=[path],
        extra_input_args=[[]],
        filter_complex=fc,
        output_args=["-map", "0:v?", "-map", "[outa]"],
        serializable={},
    )


def _build_extract(params: dict) -> OperationSettings:
    codec = params["codec"]
    info = _AUDIO_CODECS[codec]
    output_args = ["-vn", "-c:a", info["encoder"]]
    if info["bitrate_k"]:
        output_args += ["-b:a", f"{info['bitrate_k']}k"]
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Extract audio to {codec.upper()}",
        non_video_output_args=output_args,
        serializable={},
    )


def _build_channels(params: dict) -> OperationSettings:
    action = params["action"]
    if action == "downmix":
        return OperationSettings(
            name=name, display_name=display_name, description="Downmix to mono",
            non_video_output_args=["-ac", "1"], serializable={},
        )
    if action == "upmix":
        return OperationSettings(
            name=name, display_name=display_name, description="Upmix to stereo",
            non_video_output_args=["-ac", "2"], serializable={},
        )
    if action == "swap":
        return OperationSettings(
            name=name, display_name=display_name, description="Swap left/right channels",
            audio_filter=["pan=stereo|c0=c1|c1=c0"], serializable={},
        )
    if action == "left":
        return OperationSettings(
            name=name, display_name=display_name, description="Left channel only",
            audio_filter=["pan=mono|c0=c0"], serializable={},
        )
    return OperationSettings(
        name=name, display_name=display_name, description="Right channel only",
        audio_filter=["pan=mono|c0=c1"], serializable={},
    )


def _build_volume(params: dict) -> OperationSettings:
    method = params.get("method")
    if method == "gain":
        gain = params["gain_db"]
        return OperationSettings(
            name=name, display_name=display_name, description=f"Volume {gain:+.1f}dB",
            audio_filter=[f"volume={gain}dB"], serializable={},
        )
    if method == "compress":
        return OperationSettings(
            name=name,
            display_name=display_name,
            description="Dynamic range compression",
            audio_filter=["acompressor=threshold=-18dB:ratio=3:attack=20:release=250"],
            serializable={},
        )
    if method == "limit":
        return OperationSettings(
            name=name,
            display_name=display_name,
            description="Peak limiter",
            audio_filter=["alimiter=limit=-1dB"],
            serializable={},
        )
    target = params.get("target", -14)
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Loudness normalize to {target} LUFS",
        audio_filter=[f"loudnorm=I={target}:TP=-1.5:LRA=11"],
        serializable={},
    )


def _build_fade(params: dict, media: MediaInfo) -> OperationSettings:
    filters = []
    fade_in = params.get("fade_in", 0)
    fade_out = params.get("fade_out", 0)
    if fade_in:
        filters.append(f"afade=t=in:st=0:d={fade_in}")
    if fade_out:
        start = max((media.duration or 0) - fade_out, 0)
        filters.append(f"afade=t=out:st={start}:d={fade_out}")
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Fade in {fade_in}s / out {fade_out}s",
        audio_filter=filters,
        serializable={},
    )


def _build_delay(params: dict) -> OperationSettings:
    ms = params["delay_ms"]
    if ms >= 0:
        return OperationSettings(
            name=name,
            display_name=display_name,
            description=f"Delay audio {ms:.0f}ms",
            audio_filter=[f"adelay=delays={ms}:all=1"],
            serializable={},
        )
    secs = abs(ms) / 1000
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Advance audio {abs(ms):.0f}ms",
        audio_filter=[f"atrim=start={secs}", "asetpts=PTS-STARTPTS"],
        serializable={},
    )


def _build_tracks(params: dict, media: MediaInfo) -> OperationSettings:
    idx = params.get("keep_index", 0)
    output_args = []
    if media.primary_video:
        output_args += ["-map", "0:v:0"]
    output_args += ["-map", f"0:a:{idx}"]
    return OperationSettings(
        name=name,
        display_name=display_name,
        description=f"Keep only audio track {idx}",
        output_args=output_args,
        serializable={},
    )


def output_extension(params: dict) -> str | None:
    if params.get("mode") == "extract":
        return _AUDIO_CODECS[params["codec"]]["ext"]
    return None
