from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class StreamInfo:
    index: int
    codec_type: str
    codec_name: str
    codec_long_name: str = ""
    profile: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    r_frame_rate: str = ""
    avg_frame_rate: str = ""
    pix_fmt: str = ""
    color_space: str = ""
    color_transfer: str = ""
    color_primaries: str = ""
    channels: Optional[int] = None
    channel_layout: str = ""
    sample_rate: Optional[int] = None
    bit_depth: Optional[int] = None
    bit_rate: Optional[int] = None
    duration: Optional[float] = None
    tags: dict = field(default_factory=dict)

    @property
    def is_video(self) -> bool:
        return self.codec_type == "video"

    @property
    def is_audio(self) -> bool:
        return self.codec_type == "audio"

    @property
    def is_subtitle(self) -> bool:
        return self.codec_type == "subtitle"

    @property
    def frame_rate(self) -> Optional[float]:
        for rate_str in (self.avg_frame_rate, self.r_frame_rate):
            if rate_str and "/" in rate_str:
                try:
                    n, d = rate_str.split("/")
                    dv = float(d)
                    if dv > 0:
                        return round(float(n) / dv, 3)
                except (ValueError, ZeroDivisionError):
                    continue
        return None


@dataclass
class MediaInfo:
    path: Path
    format_name: str
    format_long_name: str
    duration: float
    size: int
    bit_rate: int
    streams: list[StreamInfo]
    tags: dict = field(default_factory=dict)

    @property
    def video_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.is_video]

    @property
    def audio_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.is_audio]

    @property
    def subtitle_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.is_subtitle]

    @property
    def primary_video(self) -> Optional[StreamInfo]:
        return self.video_streams[0] if self.video_streams else None

    @property
    def primary_audio(self) -> Optional[StreamInfo]:
        return self.audio_streams[0] if self.audio_streams else None


@dataclass
class HardwareCapabilities:
    videotoolbox_available: bool
    hw_encoders: set[str]
    hw_decoders: set[str]

    def has_encoder(self, codec: str) -> bool:
        return codec in self.hw_encoders

    def has_decoder(self, codec: str) -> bool:
        return codec in self.hw_decoders


@dataclass
class OperationSettings:
    name: str
    display_name: str
    description: str
    args_before_input: list[str] = field(default_factory=list)
    video_filter: list[str] = field(default_factory=list)
    audio_filter: list[str] = field(default_factory=list)
    filter_complex: Optional[str] = None
    output_args: list[str] = field(default_factory=list)
    serializable: dict = field(default_factory=dict)


@dataclass
class OutputConfig:
    path: Path


@dataclass
class FFmpegJob:
    inputs: list[Path]
    operations: list[OperationSettings]
    output: OutputConfig
    hardware: HardwareCapabilities


@dataclass
class Recipe:
    name: str
    description: str
    operations: list[dict]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "operations": self.operations,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Recipe:
        return cls(
            name=data["name"],
            description=data["description"],
            operations=data["operations"],
        )
