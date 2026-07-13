from __future__ import annotations

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
            ("Channels — mono/stereo/swap/select", "channels"),
            ("Volume / loudness normalize", "volume"),
            ("Fade in/out", "fade"),
            ("Change sample rate", "resample"),
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
            ],
            default="loudnorm_streaming",
        )
        if method == "gain":
            gain = float(prompts.ask_text("Gain (dB, negative to lower):", default="0"))
            return {"mode": "volume", "method": "gain", "gain_db": gain}
        target = -14 if method == "loudnorm_streaming" else -23
        return {"mode": "volume", "method": "loudnorm", "target": target}

    if mode == "fade":
        fade_in = float(prompts.ask_text("Fade in duration (seconds, 0 = none):", default="0"))
        fade_out = float(prompts.ask_text("Fade out duration (seconds, 0 = none):", default="3"))
        return {"mode": "fade", "fade_in": fade_in, "fade_out": fade_out}

    rate = prompts.choose("Target sample rate:", _SAMPLE_RATES, default="48000")
    return {"mode": "resample", "rate": rate}


def build(params: dict, media: MediaInfo, hardware: HardwareCapabilities) -> OperationSettings:
    mode = params["mode"]
    if mode == "extract":
        return _build_extract(params)
    if mode == "mute":
        return OperationSettings(
            name=name, display_name=display_name, description="Mute (remove audio)",
            output_args=["-an"], serializable={},
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
            output_args=["-ar", params["rate"]], serializable={},
        )
    raise ValueError(f"unknown sound mode: {mode}")


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
        output_args=output_args,
        serializable={},
    )


def _build_channels(params: dict) -> OperationSettings:
    action = params["action"]
    if action == "downmix":
        return OperationSettings(
            name=name, display_name=display_name, description="Downmix to mono",
            output_args=["-ac", "1"], serializable={},
        )
    if action == "upmix":
        return OperationSettings(
            name=name, display_name=display_name, description="Upmix to stereo",
            output_args=["-ac", "2"], serializable={},
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
    if params.get("method") == "gain":
        gain = params["gain_db"]
        return OperationSettings(
            name=name, display_name=display_name, description=f"Volume {gain:+.1f}dB",
            audio_filter=[f"volume={gain}dB"], serializable={},
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


def output_extension(params: dict) -> str | None:
    if params.get("mode") == "extract":
        return _AUDIO_CODECS[params["codec"]]["ext"]
    return None
