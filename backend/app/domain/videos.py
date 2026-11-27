"""Domain layer for video discovery: entities, enums and domain exceptions."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from app.domain.downloads import DownloadStatus


class LivestreamStatus(StrEnum):
    """Livestream lifecycle state reported by the YouTube API."""

    NONE = "none"
    UPCOMING = "upcoming"
    LIVE = "live"
    COMPLETED = "completed"


class ProcessingStatus(StrEnum):
    """Processing pipeline state for a discovered video."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class VideoDiscoveryError(Exception):
    """Base exception for video discovery failures."""


class QuotaExhaustedError(VideoDiscoveryError):
    """Raised when the YouTube API quota is exhausted during a discovery run."""


class ChannelResolutionError(VideoDiscoveryError):
    """Raised when a registered channel URL cannot be resolved to a YouTube channel ID."""

    def __init__(self, message: str, channel_id: int | None = None) -> None:
        super().__init__(message)
        self.channel_id = channel_id


class DiscoveryAlreadyRunningError(VideoDiscoveryError):
    """Raised when a discovery run is already in progress."""


@dataclass(frozen=True)
class VideoEntity:
    id: int
    channel_id: int | None
    youtube_video_id: str
    title: str
    description: str
    video_url: str
    thumbnail_url: str | None
    duration_seconds: int
    published_at: datetime
    livestream_status: LivestreamStatus
    discovered_at: datetime
    processing_status: ProcessingStatus
    download_status: DownloadStatus
    local_video_path: str | None
    actual_resolution: str | None
    file_size_bytes: int | None
    video_codec: str | None
    download_progress: float
    downloaded_bytes: int
    total_bytes: int | None
    download_requested: bool
    download_started_at: datetime | None
    download_completed_at: datetime | None
    download_retry_count: int
    download_error: str | None
    created_at: datetime
    updated_at: datetime
    channel_name: str | None = None
    youtube_channel_id: str | None = None
    is_excluded: bool = False
    excluded_keywords: list[str] = field(default_factory=list)
    intermediates_cleaned: bool = False
    intermediates_cleaned_at: datetime | None = None


@dataclass(frozen=True)
class VideoSummary:
    total: int
    pending: int
    today: int
    latest_discovery_at: datetime | None
    eligible: int = 0
    excluded: int = 0


@dataclass(frozen=True)
class VideoPage:
    items: list[VideoEntity]
    total: int
    page: int
    page_size: int
    total_pages: int


@dataclass
class DiscoveryRunSummary:
    channels_checked: int = 0
    channels_skipped: int = 0
    videos_found: int = 0
    new_videos_added: int = 0
    existing_videos_skipped: int = 0
    videos_rejected_duration: int = 0
    videos_rejected_filter: int = 0
    livestreams_deferred: int = 0
    failed_channels: list[str] = field(default_factory=list)
    api_requests_made: int = 0
    search_requests_made: int = 0
    quota_reset_at: datetime | None = None
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
