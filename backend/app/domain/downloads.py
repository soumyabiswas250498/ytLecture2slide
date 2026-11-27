"""Domain layer for video acquisition: contracts, enums, progress and exceptions."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from threading import Event
from typing import Protocol


class DownloadStatus(StrEnum):
    """Acquisition lifecycle state for a discovered video."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DownloadError(Exception):
    """Base exception for video download failures."""

    def __init__(self, message: str, *, recoverable: bool = False) -> None:
        super().__init__(message)
        self.recoverable = recoverable


class VideoNotFoundError(DownloadError):
    """Raised when the requested video does not exist."""


class DownloadAlreadyInProgressError(DownloadError):
    """Raised when a download or conflicting operation is already running for a video."""


class DownloadAlreadyCompletedError(DownloadError):
    """Raised when attempting to download a video that already has a verified local file."""


class InvalidDownloadStateError(DownloadError):
    """Raised when a download action is invalid for the video's current state."""


class InsufficientDiskSpaceError(DownloadError):
    """Raised when available disk space is below the configured minimum threshold."""


class DownloadCancelledError(DownloadError):
    """Raised when an active download is cancelled by the user."""


class DownloadInterruptedError(DownloadError):
    """Raised when an active download is interrupted by server shutdown/SIGTERM."""


class MediaValidationError(DownloadError):
    """Raised when FFprobe validation fails for a downloaded media file."""


class UnsupportedFormatError(DownloadError):
    """Raised when no compliant video-only stream within resolution limits is available."""


@dataclass(frozen=True)
class DownloadProgress:
    """Real-time or persisted progress snapshot for a video download."""

    video_id: int
    youtube_video_id: str
    status: DownloadStatus
    progress_percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bytes_per_sec: float | None = None
    eta_seconds: float | None = None
    is_live: bool = False
    error: str | None = None


@dataclass(frozen=True)
class MediaProbeResult:
    """Validated media metadata extracted by FFprobe."""

    width: int
    height: int
    resolution_label: str
    duration_seconds: float
    video_codec: str
    has_audio: bool
    file_size_bytes: int


@dataclass(frozen=True)
class DownloadRequest:
    """Input contract for the video downloader adapter."""

    video_id: int
    youtube_video_id: str
    video_url: str
    destination_dir: Path
    max_resolution: int = 720
    audio_enabled: bool = False
    connect_timeout_seconds: int = 30
    inactivity_timeout_seconds: int = 120
    max_total_timeout_seconds: int | None = None


@dataclass(frozen=True)
class DownloadResult:
    """Output contract returned by a successful download & validation."""

    local_path: Path
    probe: MediaProbeResult


@dataclass
class BulkDownloadSummary:
    """Summary returned when initiating bulk downloads."""

    started_ids: list[int] = field(default_factory=list)
    skipped: list[dict[str, str | int]] = field(default_factory=list)
    errors: list[dict[str, str | int]] = field(default_factory=list)


ProgressCallback = Callable[[DownloadProgress], None]


class VideoDownloaderAdapter(Protocol):
    """Interface isolating yt-dlp or alternative downloaders from business logic."""

    def download(
        self,
        request: DownloadRequest,
        *,
        on_progress: ProgressCallback | None = None,
        cancel_event: Event | None = None,
        shutdown_event: Event | None = None,
    ) -> Path:
        """Download the requested video and return the local file path."""
        ...


class MediaProbeValidator(Protocol):
    """Interface for validating downloaded video files."""

    def validate(
        self,
        file_path: Path,
        *,
        max_resolution: int,
        require_no_audio: bool = True,
        cancel_event: Event | None = None,
        shutdown_event: Event | None = None,
    ) -> MediaProbeResult:
        """Inspect and validate a local media file."""
        ...
