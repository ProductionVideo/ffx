"""Single-screen operation forms - the first is Convert.

Instead of six sequential questions, every Convert decision sits on one
screen with live dependencies: changing the codec refilters the container
list, swaps the audio default, and recomputes the quality tiers' size
estimates; changing the engine or audio codec refreshes the tiers too.
Dismisses with the exact params dict prompt() would have produced, so
build(), recipes, and the classic wizard all stay untouched.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from ffx import presets as preset_calc
from ffx.models import HardwareCapabilities, MediaInfo
from ffx.operations import convert as convert_op
from ffx.tui.screens import PromptScreen

_CODEC_CHOICES = [
    ("H.264", "h264"),
    ("H.265 / HEVC", "hevc"),
    ("AV1", "av1"),
    ("VP9", "vp9"),
    ("ProRes", "prores"),
    ("DNxHR (Avid)", "dnxhr"),
    ("HAP (VJ / media servers)", "hap"),
    ("MPEG-2", "mpeg2"),
    ("Copy (no re-encode)", "copy_v"),
]

_AUDIO_CHOICES = [
    ("AAC", "aac"),
    ("Opus", "opus"),
    ("MP3", "mp3"),
    ("AC-3", "ac3"),
    ("FLAC", "flac"),
    ("PCM / WAV", "pcm"),
    ("Copy (no re-encode)", "copy"),
]

_PROFILE_SOURCES = {
    "prores": ("ProRes profile", convert_op._PRORES_PROFILES, convert_op._PRORES_KBPS_1080P30, "3"),
    "dnxhr": ("DNxHR profile", convert_op._DNXHR_PROFILES, convert_op._DNXHR_KBPS_1080P30, "dnxhr_hq"),
    "hap": ("HAP flavour", convert_op._HAP_FORMATS, convert_op._HAP_KBPS_1080P30, "hap"),
}


class ConvertScreen(PromptScreen):
    DEFAULT_CSS = PromptScreen.DEFAULT_CSS + """
    ConvertScreen .form-row {
        height: auto;
        margin-top: 1;
    }
    ConvertScreen .form-field {
        width: 1fr;
        height: auto;
        margin-right: 2;
    }
    ConvertScreen .form-field Label {
        color: $text-muted;
    }
    ConvertScreen #form-warn {
        color: $warning;
        height: auto;
    }
    ConvertScreen #add {
        margin-top: 1;
    }
    """

    def __init__(self, media: MediaInfo, hardware: HardwareCapabilities):
        super().__init__(
            "Convert — everything on one screen",
            hint="Tab between fields; estimates update live.",
            back_enabled=True,
        )
        self._media = media
        self._hardware = hardware
        self._quality_rows: list = []
        self._syncing = False
        # (vcodec, engine, acodec) the quality tiers were last computed
        # for. set_options() itself emits async Changed events, so a
        # naive "recompute every sync" ping-pongs forever - only rebuild
        # when an input the tiers depend on actually changed.
        self._quality_key: tuple | None = None

    # ---- layout ----

    def compose_body(self) -> ComposeResult:
        hap_reason = convert_op.hap_unavailable_reason(self._hardware)
        codec_choices = [c for c in _CODEC_CHOICES if not (c[1] == "hap" and hap_reason)]
        with Horizontal(classes="form-row"):
            with Vertical(classes="form-field"):
                yield Label("Video codec")
                yield Select(codec_choices, value="h264", allow_blank=False, id="codec")
            with Vertical(classes="form-field"):
                yield Label("Container")
                yield Select([("MP4", "mp4")], value="mp4", allow_blank=False, id="container")
            with Vertical(classes="form-field"):
                yield Label("Audio")
                yield Select(_AUDIO_CHOICES, value="copy", allow_blank=False, id="audio")
        with Horizontal(classes="form-row", id="standard-row"):
            with Vertical(classes="form-field"):
                yield Label("Encoder")
                yield Select([("Software", "software")], value="software", allow_blank=False, id="engine")
            with Vertical(classes="form-field"):
                yield Label("Quality")
                yield Select([("Manual", "manual")], value="manual", allow_blank=False, id="quality")
        with Horizontal(classes="form-row", id="profile-row"):
            with Vertical(classes="form-field"):
                yield Label("Profile", id="profile-label")
                yield Select([("-", "-")], value="-", allow_blank=False, id="profile")
        with Horizontal(classes="form-row", id="value-row"):
            with Vertical(classes="form-field"):
                yield Label("Value", id="value-label")
                yield Input(id="value")
        with Horizontal(classes="form-row", id="twopass-row"):
            yield Checkbox("Two-pass encode (slower, lands on target)", id="twopass")
        yield Static("", id="form-warn")
        yield Button("Add to pipeline", variant="primary", id="add")

    def on_mount(self) -> None:
        self._sync(codec_changed=True)
        self.query_one("#codec", Select).focus()

    # ---- live dependencies ----

    def on_select_changed(self, event: Select.Changed) -> None:
        if self._syncing:
            return
        self._sync(codec_changed=event.select.id == "codec")

    def _sync(self, *, codec_changed: bool) -> None:
        self._syncing = True
        try:
            self._apply(codec_changed)
        finally:
            self._syncing = False

    def _apply(self, codec_changed: bool) -> None:
        vcodec = self.query_one("#codec", Select).value
        audio_select = self.query_one("#audio", Select)

        if codec_changed:
            choices, default = convert_op.container_options(vcodec, self._media)
            container = self.query_one("#container", Select)
            container.set_options(choices)
            container.value = default
            audio_select.value = convert_op._DEFAULT_AUDIO.get(vcodec, "copy")

        profile_row = self.query_one("#profile-row")
        if vcodec in _PROFILE_SOURCES:
            title, profiles, kbps, default = _PROFILE_SOURCES[vcodec]
            self.query_one("#profile-label", Label).update(title)
            if codec_changed:
                profile = self.query_one("#profile", Select)
                profile.set_options(convert_op._profile_choices(profiles, kbps, self._media))
                profile.value = default
            profile_row.display = True
        else:
            profile_row.display = False

        standard = vcodec in convert_op._VIDEO_CODECS
        engine_select = self.query_one("#engine", Select)
        prores_hw = vcodec == "prores" and self._hardware.has_encoder("prores_videotoolbox")
        if standard or prores_hw:
            if codec_changed:
                if prores_hw:
                    options, default = (
                        [("Hardware — fast (Apple Silicon)", "hardware"), ("Software — best quality", "software")],
                        "hardware",
                    )
                else:
                    options, default = convert_op.engine_options(vcodec, self._hardware)
                engine_select.set_options(options)
                engine_select.value = default
                engine_select.disabled = len(options) == 1
        engine = engine_select.value if (standard or prores_hw) else "software"

        quality_select = self.query_one("#quality", Select)
        self.query_one("#standard-row").display = standard or prores_hw
        quality_select.display = standard
        quality_key = (vcodec, engine, audio_select.value)
        if standard and quality_key != self._quality_key:
            self._quality_key = quality_key
            previous = quality_select.value
            rows, options, default = convert_op.quality_options(
                vcodec, engine, self._media, self._hardware, audio_select.value
            )
            self._quality_rows = rows
            tokens = {value for _, value in options}
            quality_select.set_options(options)
            quality_select.value = previous if previous in tokens and not codec_changed else default

        self._sync_value_row(vcodec, engine, standard, quality_select.value if standard else None)
        self.query_one("#twopass-row").display = (
            standard
            and engine == "software"
            and standard
            and str(quality_select.value) != "manual"
        )
        self.query_one("#form-warn", Static).update("")

    def _sync_value_row(self, vcodec: str, engine: str, standard: bool, quality_token) -> None:
        row = self.query_one("#value-row")
        if not standard or quality_token not in ("manual", "target"):
            row.display = False
            return
        label = self.query_one("#value-label", Label)
        box = self.query_one("#value", Input)
        if quality_token == "target":
            label.update("Target size (MB)")
            box.value = "25"
        elif engine == "hardware":
            label.update("Quality (1-100, higher = better)")
            box.value = "65"
        else:
            label.update(f"Manual quality — {convert_op._MANUAL_QUALITY_HINT[vcodec]}")
            box.value = convert_op._MANUAL_QUALITY_DEFAULT[vcodec]
        row.display = True

    # ---- submit ----

    def on_button_pressed(self, event: Button.Pressed) -> None:
        params = self._collect()
        if params is not None:
            self.dismiss((params, False))

    def _collect(self) -> dict | None:
        vcodec = self.query_one("#codec", Select).value
        params: dict = {
            "container": self.query_one("#container", Select).value,
            "vcodec": vcodec,
            "acodec": self.query_one("#audio", Select).value,
        }

        if vcodec == "copy_v":
            return params
        if vcodec in _PROFILE_SOURCES:
            key = {"prores": "prores_profile", "dnxhr": "dnxhr_profile", "hap": "hap_format"}[vcodec]
            params[key] = self.query_one("#profile", Select).value
            if vcodec == "prores" and self._hardware.has_encoder("prores_videotoolbox"):
                params["engine"] = self.query_one("#engine", Select).value
            elif vcodec == "prores":
                params["engine"] = "software"
            return params

        engine = self.query_one("#engine", Select).value
        params["engine"] = engine
        token = str(self.query_one("#quality", Select).value)

        if token.startswith("tier:"):
            row = self._quality_rows[int(token.split(":")[1])]
            params.update({"quality_mode": "bitrate", "video_kbps": row.target_video_kbps})
        elif token == "target":
            number = self._number("Target size must be a number of MB")
            if number is None:
                return None
            result = preset_calc.target_size_video_kbps(
                number, self._media.duration or 0.0, convert_op.audio_kbps_for(params["acodec"], self._media)
            )
            if not result.feasible:
                self.query_one("#form-warn", Static).update(
                    f"{number:g} MB is a very tight budget — the output will likely come in larger."
                )
            params.update(
                {"quality_mode": "target_size", "video_kbps": result.video_kbps, "target_size_mb": number}
            )
        elif engine == "hardware":
            number = self._number("Quality must be a whole number 1-100")
            if number is None or not 1 <= number <= 100:
                self.query_one("#form-warn", Static).update("Quality must be 1-100")
                return None
            params.update({"quality_mode": "hw_quality", "hw_quality": int(number)})
        else:
            number = self._number("Manual quality must be a number")
            if number is None:
                return None
            params.update({"quality_mode": "manual", "manual_value": int(number)})

        if self.query_one("#twopass-row").display and params.get("quality_mode") in ("bitrate", "target_size"):
            params["two_pass"] = self.query_one("#twopass", Checkbox).value
        return params

    def _number(self, error: str) -> float | None:
        text = self.query_one("#value", Input).value.strip()
        try:
            return float(text)
        except ValueError:
            self.query_one("#form-warn", Static).update(error)
            return None
