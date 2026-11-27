"""FastAPI routes for video listing and discovery triggering."""

import logging
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.domain.downloads import BulkDownloadSummary, DownloadProgress, DownloadStatus
from app.domain.videos import (
    DiscoveryRunSummary,
    LivestreamStatus,
    ProcessingStatus,
    VideoEntity,
)
from app.infrastructure.youtube_client import YouTubeApiClient
from app.repositories.channels import ChannelRepository
from app.repositories.videos import VideoRepository
from app.services.discovery import DiscoveryService
from app.services.downloader import VideoDownloadService

logger = logging.getLogger("app.api.videos")

videos_router = APIRouter(prefix="/api/v1/videos", tags=["videos"])
discovery_router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])


# ------------------------------------------------------------------
# Dependency helpers
# ------------------------------------------------------------------


def _get_video_repo(request: Request) -> VideoRepository:
    return VideoRepository(request.app.state.sessions)


def _get_download_service(request: Request) -> VideoDownloadService:
    service: VideoDownloadService = request.app.state.download_service
    return service


def _get_discovery_service(request: Request) -> DiscoveryService:
    settings = request.app.state.settings
    if not settings.youtube_api_key:
        raise ValueError(
            "YOUTUBE_API_KEY is not configured. Set it in the environment before running discovery."
        )
    yt_client = YouTubeApiClient(
        settings.youtube_api_key,
        quota_limit=settings.discovery_quota_limit,
        search_quota_limit=settings.discovery_search_quota_limit,
    )
    channel_repo = ChannelRepository(request.app.state.sessions)
    video_repo = VideoRepository(request.app.state.sessions)
    exclusion_service = getattr(request.app.state, "exclusion_service", None)
    return DiscoveryService(
        youtube_client=yt_client,
        channel_repo=channel_repo,
        video_repo=video_repo,
        settings=settings,
        exclusion_service=exclusion_service,
    )


VideoRepoDep = Annotated[VideoRepository, Depends(_get_video_repo)]
DiscoveryServiceDep = Annotated[DiscoveryService, Depends(_get_discovery_service)]
DownloadServiceDep = Annotated[VideoDownloadService, Depends(_get_download_service)]


# ------------------------------------------------------------------
# Response schemas
# ------------------------------------------------------------------


class VideoResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: int
    channel_id: int | None
    channel_name: str | None = None
    youtube_channel_id: str | None = None
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
    is_excluded: bool = False
    excluded_keywords: list[str] = []

    @classmethod
    def from_entity(cls, entity: VideoEntity) -> "VideoResponse":
        return cls(
            id=entity.id,
            channel_id=entity.channel_id,
            channel_name=entity.channel_name,
            youtube_channel_id=entity.youtube_channel_id,
            youtube_video_id=entity.youtube_video_id,
            title=entity.title,
            description=entity.description,
            video_url=entity.video_url,
            thumbnail_url=entity.thumbnail_url,
            duration_seconds=entity.duration_seconds,
            published_at=entity.published_at,
            livestream_status=entity.livestream_status,
            discovered_at=entity.discovered_at,
            processing_status=entity.processing_status,
            download_status=entity.download_status,
            local_video_path=entity.local_video_path,
            actual_resolution=entity.actual_resolution,
            file_size_bytes=entity.file_size_bytes,
            video_codec=entity.video_codec,
            download_progress=entity.download_progress,
            downloaded_bytes=entity.downloaded_bytes,
            total_bytes=entity.total_bytes,
            download_requested=entity.download_requested,
            download_started_at=entity.download_started_at,
            download_completed_at=entity.download_completed_at,
            download_retry_count=entity.download_retry_count,
            download_error=entity.download_error,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            is_excluded=entity.is_excluded,
            excluded_keywords=entity.excluded_keywords,
        )


class DownloadProgressResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    video_id: int
    youtube_video_id: str
    status: DownloadStatus
    progress_percent: float
    downloaded_bytes: int
    total_bytes: int | None
    speed_bytes_per_sec: float | None
    eta_seconds: float | None
    is_live: bool
    error: str | None

    @classmethod
    def from_progress(cls, progress: DownloadProgress) -> "DownloadProgressResponse":
        return cls(
            video_id=progress.video_id,
            youtube_video_id=progress.youtube_video_id,
            status=progress.status,
            progress_percent=progress.progress_percent,
            downloaded_bytes=progress.downloaded_bytes,
            total_bytes=progress.total_bytes,
            speed_bytes_per_sec=progress.speed_bytes_per_sec,
            eta_seconds=progress.eta_seconds,
            is_live=progress.is_live,
            error=progress.error,
        )


class BulkDownloadRequest(BaseModel):
    video_ids: list[int] = Field(min_length=1, max_length=100)


class BulkDownloadItemOutcome(BaseModel):
    video_id: int
    reason: str


class BulkDownloadResponse(BaseModel):
    started_ids: list[int]
    skipped: list[BulkDownloadItemOutcome]
    errors: list[BulkDownloadItemOutcome]

    @classmethod
    def from_summary(cls, summary: BulkDownloadSummary) -> "BulkDownloadResponse":
        return cls(
            started_ids=summary.started_ids,
            skipped=[
                BulkDownloadItemOutcome(
                    video_id=int(item["video_id"]),
                    reason=str(item["reason"]),
                )
                for item in summary.skipped
            ],
            errors=[
                BulkDownloadItemOutcome(
                    video_id=int(item["video_id"]),
                    reason=str(item["reason"]),
                )
                for item in summary.errors
            ],
        )


class VideoListResponse(BaseModel):
    items: list[VideoResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class VideoSummaryResponse(BaseModel):
    total: int
    pending: int
    today: int
    latest_discovery_at: datetime | None
    eligible: int = 0
    excluded: int = 0


class DiscoveryRunResponse(BaseModel):
    channels_checked: int
    channels_skipped: int
    videos_found: int
    new_videos_added: int
    existing_videos_skipped: int
    videos_rejected_duration: int
    videos_rejected_filter: int
    livestreams_deferred: int
    failed_channels: list[str]
    api_requests_made: int
    search_requests_made: int = 0
    quota_reset_at: datetime | None = None
    duration_seconds: float
    errors: list[str]

    @classmethod
    def from_summary(cls, summary: DiscoveryRunSummary) -> "DiscoveryRunResponse":
        return cls(
            channels_checked=summary.channels_checked,
            channels_skipped=summary.channels_skipped,
            videos_found=summary.videos_found,
            new_videos_added=summary.new_videos_added,
            existing_videos_skipped=summary.existing_videos_skipped,
            videos_rejected_duration=summary.videos_rejected_duration,
            videos_rejected_filter=summary.videos_rejected_filter,
            livestreams_deferred=summary.livestreams_deferred,
            failed_channels=summary.failed_channels,
            api_requests_made=summary.api_requests_made,
            search_requests_made=summary.search_requests_made,
            quota_reset_at=summary.quota_reset_at,
            duration_seconds=summary.duration_seconds,
            errors=summary.errors,
        )


# ------------------------------------------------------------------
# Video routes
# ------------------------------------------------------------------


@videos_router.get("/summary", response_model=VideoSummaryResponse)
def get_video_summary(repo: VideoRepoDep) -> VideoSummaryResponse:
    summary = repo.get_summary()
    return VideoSummaryResponse(
        total=summary.total,
        pending=summary.pending,
        today=summary.today,
        latest_discovery_at=summary.latest_discovery_at,
        eligible=summary.eligible,
        excluded=summary.excluded,
    )


@videos_router.get("", response_model=VideoListResponse)
def list_videos(
    repo: VideoRepoDep,
    search: str | None = Query(default=None, max_length=200),
    channel_id: int | None = Query(default=None),
    processing_status: ProcessingStatus | None = Query(default=None),  # noqa: B008
    download_status: DownloadStatus | None = Query(default=None),  # noqa: B008
    eligibility: Literal["all", "eligible", "excluded"] = Query(default="all"),
    published_after: datetime | None = Query(default=None),  # noqa: B008
    published_before: datetime | None = Query(default=None),  # noqa: B008
    sort_by: str = Query(  # noqa: B008
        default="published_at",
        pattern="^(published_at|discovered_at|title|duration_seconds)$",
    ),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),  # noqa: B008
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> VideoListResponse:
    result = repo.list_videos(
        search=search,
        channel_id=channel_id,
        processing_status=processing_status,
        download_status=download_status,
        eligibility=eligibility,
        published_after=published_after,
        published_before=published_before,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    return VideoListResponse(
        items=[VideoResponse.from_entity(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@videos_router.get("/downloads/active", response_model=list[DownloadProgressResponse])
def get_active_downloads(service: DownloadServiceDep) -> list[DownloadProgressResponse]:
    """Return real-time progress for all currently active downloads."""
    return [DownloadProgressResponse.from_progress(p) for p in service.get_active_progress()]


@videos_router.post(
    "/downloads/bulk",
    response_model=BulkDownloadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_bulk_download(
    payload: BulkDownloadRequest,
    service: DownloadServiceDep,
) -> BulkDownloadResponse:
    """Start downloads for multiple selected videos without blocking request handling."""
    summary = service.start_bulk_download(payload.video_ids)
    return BulkDownloadResponse.from_summary(summary)


@videos_router.get("/{video_id}", response_model=VideoResponse)
def get_video(video_id: int, repo: VideoRepoDep) -> VideoResponse:
    entity = repo.get_by_id(video_id)
    if entity is None:
        return JSONResponse(  # type: ignore[return-value]
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": "video_not_found", "message": "Video not found."}},
        )
    return VideoResponse.from_entity(entity)


@videos_router.post(
    "/{video_id}/download",
    response_model=VideoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_video_download(video_id: int, service: DownloadServiceDep) -> VideoResponse:
    """Start a background download for an individual discovered video."""
    entity = service.start_download(video_id)
    return VideoResponse.from_entity(entity)


@videos_router.get("/{video_id}/download/progress", response_model=DownloadProgressResponse)
def get_video_download_progress(
    video_id: int, service: DownloadServiceDep
) -> DownloadProgressResponse:
    """Retrieve live or persisted download progress for a video."""
    progress = service.get_progress(video_id)
    return DownloadProgressResponse.from_progress(progress)


@videos_router.post("/{video_id}/download/cancel", response_model=VideoResponse)
def cancel_video_download(video_id: int, service: DownloadServiceDep) -> VideoResponse:
    """Cancel an active download for a video."""
    entity = service.cancel_download(video_id)
    return VideoResponse.from_entity(entity)


@videos_router.post(
    "/{video_id}/download/retry",
    response_model=VideoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_video_download(video_id: int, service: DownloadServiceDep) -> VideoResponse:
    """Retry a failed or cancelled video download."""
    entity = service.retry_download(video_id)
    return VideoResponse.from_entity(entity)


@videos_router.delete("/{video_id}/download", response_model=VideoResponse)
def delete_local_video(video_id: int, service: DownloadServiceDep) -> VideoResponse:
    """Remove a locally downloaded video file and reset download metadata."""
    entity = service.delete_local_video(video_id)
    return VideoResponse.from_entity(entity)


# ------------------------------------------------------------------
# Discovery routes
# ------------------------------------------------------------------


@discovery_router.post("/run", response_model=DiscoveryRunResponse)
def run_discovery_all(service: DiscoveryServiceDep) -> DiscoveryRunResponse:
    """Trigger video discovery for all active channels."""
    summary = service.discover_all_channels()
    return DiscoveryRunResponse.from_summary(summary)


@discovery_router.post("/channel/{channel_id}", response_model=DiscoveryRunResponse)
def run_discovery_channel(channel_id: int, service: DiscoveryServiceDep) -> DiscoveryRunResponse:
    """Trigger video discovery for a single registered channel."""
    summary = service.discover_one_channel(channel_id)
    return DiscoveryRunResponse.from_summary(summary)
