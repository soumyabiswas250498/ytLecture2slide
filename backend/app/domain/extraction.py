"""Reusable frame extraction contracts, independent of persistence and HTTP."""

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CLEANED = "cleaned"


class ExtractionError(Exception):
    """Invalid media or unsuccessful extraction."""


class ExtractionConflict(ExtractionError):
    """An incompatible operation is already in progress or completed."""


class ExtractionCancelled(ExtractionError):
    """The caller requested cancellation."""


class CancellationSignal(Protocol):
    def is_set(self) -> bool: ...


class FrameMetadata(BaseModel):
    filename: str = Field(pattern=r"^frame_\d{9,}\.png$")
    requested_timestamp: float = Field(ge=0, allow_inf_nan=False)
    actual_timestamp: float = Field(ge=0, allow_inf_nan=False)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ExtractionResult(BaseModel):
    video_id: str
    source_path: str
    source_size_bytes: int
    source_mtime_ns: int
    video_duration: float = Field(gt=0, allow_inf_nan=False)
    interval_seconds: float | None
    start_timestamp: float
    end_timestamp: float
    frames: list[FrameMetadata]
    frame_count: int
    processing_duration: float = Field(ge=0, allow_inf_nan=False)
    status: ExtractionStatus = ExtractionStatus.EXTRACTED
    manifest_version: int = 1
    strategy: Literal["seek", "sequential"] = "seek"
    image_format: Literal["png"] = "png"
    lossless: bool = True
    decoder_threads: int = 1
    source_codec: str = "unknown"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FrameExtractor(Protocol):
    def extract(
        self,
        source: Path,
        output: Path,
        *,
        video_id: str,
        interval: float = 60,
        start: float = 0,
        end: float | None = None,
        timestamps: list[float] | None = None,
        on_progress: "ProgressCallback | None" = None,
        cancel: CancellationSignal | None = None,
    ) -> ExtractionResult: ...


class ProgressCallback(Protocol):
    def __call__(self, count: int, expected: int) -> None: ...
