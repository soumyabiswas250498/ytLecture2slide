"""Repository for video records — data-access layer only, no business logic."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from math import ceil
from typing import Any, Literal

from sqlalchemy import ColumnElement, func, inspect, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session, sessionmaker

from app.domain.downloads import DownloadStatus
from app.domain.exclusion import ExclusionMatchResult
from app.domain.videos import (
    LivestreamStatus,
    ProcessingStatus,
    VideoEntity,
    VideoPage,
    VideoSummary,
)
from app.infrastructure.models import ChannelRecord, VideoRecord, utc_now


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_excluded_keywords(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _to_entity(record: VideoRecord) -> VideoEntity:
    return VideoEntity(
        id=record.id,
        channel_id=record.channel_id,
        youtube_video_id=record.youtube_video_id,
        title=record.title,
        description=record.description,
        video_url=record.video_url,
        thumbnail_url=record.thumbnail_url,
        duration_seconds=record.duration_seconds,
        published_at=_ensure_utc(record.published_at),
        livestream_status=LivestreamStatus(record.livestream_status),
        discovered_at=_ensure_utc(record.discovered_at),
        processing_status=ProcessingStatus(record.processing_status),
        download_status=DownloadStatus(record.download_status),
        local_video_path=record.local_video_path,
        actual_resolution=record.actual_resolution,
        file_size_bytes=record.file_size_bytes,
        video_codec=record.video_codec,
        download_progress=record.download_progress,
        downloaded_bytes=record.downloaded_bytes,
        total_bytes=record.total_bytes,
        download_requested=record.download_requested,
        download_started_at=(
            _ensure_utc(record.download_started_at)
            if record.download_started_at is not None
            else None
        ),
        download_completed_at=(
            _ensure_utc(record.download_completed_at)
            if record.download_completed_at is not None
            else None
        ),
        download_retry_count=record.download_retry_count,
        download_error=record.download_error,
        created_at=_ensure_utc(record.created_at),
        updated_at=_ensure_utc(record.updated_at),
        channel_name=record.channel_name,
        youtube_channel_id=record.youtube_channel_id,
        is_excluded=record.is_excluded,
        excluded_keywords=_parse_excluded_keywords(record.matched_exclusion_keywords),
    )


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class VideoRepository:
    """SQLAlchemy repository for video records."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create_or_skip(
        self,
        *,
        channel_id: int | None,
        youtube_video_id: str,
        title: str,
        description: str,
        video_url: str,
        thumbnail_url: str | None,
        duration_seconds: int,
        published_at: datetime,
        livestream_status: LivestreamStatus,
        discovered_at: datetime,
        channel_name: str | None = None,
        youtube_channel_id: str | None = None,
        is_excluded: bool = False,
        excluded_keywords: list[str] | None = None,
    ) -> tuple[VideoEntity, bool]:
        """Insert a new video or skip if youtube_video_id already exists.

        Returns (entity, created). Never resets existing processing_status.
        """
        now = utc_now()
        with self._sessions() as session:
            # Check if already exists first to avoid exception-based flow.
            existing = session.scalar(
                select(VideoRecord).where(VideoRecord.youtube_video_id == youtube_video_id)
            )
            if existing is not None:
                return _to_entity(existing), False

            resolved_channel_name = channel_name
            resolved_yt_channel_id = youtube_channel_id
            if channel_id is not None and (
                resolved_channel_name is None or resolved_yt_channel_id is None
            ):
                ch = session.get(ChannelRecord, channel_id)
                if ch is not None:
                    if resolved_channel_name is None:
                        resolved_channel_name = ch.name
                    if resolved_yt_channel_id is None:
                        resolved_yt_channel_id = ch.youtube_channel_id

            record = VideoRecord(
                channel_id=channel_id,
                channel_name=resolved_channel_name,
                youtube_channel_id=resolved_yt_channel_id,
                youtube_video_id=youtube_video_id,
                title=title,
                description=description,
                video_url=video_url,
                thumbnail_url=thumbnail_url,
                duration_seconds=duration_seconds,
                published_at=published_at,
                livestream_status=livestream_status.value,
                discovered_at=discovered_at,
                processing_status=ProcessingStatus.PENDING.value,
                download_status=DownloadStatus.PENDING.value,
                download_progress=0.0,
                downloaded_bytes=0,
                total_bytes=None,
                download_requested=False,
                download_retry_count=0,
                is_excluded=is_excluded,
                matched_exclusion_keywords=(
                    json.dumps(excluded_keywords, ensure_ascii=False) if excluded_keywords else None
                ),
                created_at=now,
                updated_at=now,
            )
            try:
                session.add(record)
                session.commit()
                session.refresh(record)
                return _to_entity(record), True
            except IntegrityError:
                session.rollback()
                # Race condition: another concurrent insert won. Fetch and return existing.
                existing = session.scalar(
                    select(VideoRecord).where(VideoRecord.youtube_video_id == youtube_video_id)
                )
                if existing is None:
                    raise  # Unexpected — re-raise original error.
                return _to_entity(existing), False

    def get_by_id(self, video_id: int) -> VideoEntity | None:
        with self._sessions() as session:
            record = session.get(VideoRecord, video_id)
            return _to_entity(record) if record is not None else None

    def find_by_youtube_id(self, youtube_video_id: str) -> VideoEntity | None:
        with self._sessions() as session:
            record = session.scalar(
                select(VideoRecord).where(VideoRecord.youtube_video_id == youtube_video_id)
            )
            return _to_entity(record) if record is not None else None

    def list_videos(
        self,
        *,
        search: str | None = None,
        channel_id: int | None = None,
        processing_status: ProcessingStatus | None = None,
        download_status: DownloadStatus | None = None,
        eligibility: Literal["all", "eligible", "excluded"] = "all",
        published_after: datetime | None = None,
        published_before: datetime | None = None,
        sort_by: str = "published_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> VideoPage:
        with self._sessions() as session:
            filters = self._build_filters(
                search=search,
                channel_id=channel_id,
                processing_status=processing_status,
                download_status=download_status,
                eligibility=eligibility,
                published_after=published_after,
                published_before=published_before,
            )

            total = session.scalar(select(func.count(VideoRecord.id)).where(*filters)) or 0

            total_pages = max(1, ceil(total / page_size)) if total > 0 else 1
            offset = (page - 1) * page_size

            order_col = self._resolve_sort_column(sort_by)
            order_expr = order_col.desc() if sort_order.lower() == "desc" else order_col.asc()

            records = session.scalars(
                select(VideoRecord)
                .where(*filters)
                .order_by(order_expr)
                .offset(offset)
                .limit(page_size)
            ).all()

            return VideoPage(
                items=[_to_entity(record) for record in records],
                total=total,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
            )

    def get_summary(self) -> VideoSummary:
        with self._sessions() as session:
            today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            row = session.execute(
                select(
                    func.count(VideoRecord.id),
                    func.count(VideoRecord.id).filter(
                        VideoRecord.processing_status == ProcessingStatus.PENDING.value
                    ),
                    func.count(VideoRecord.id).filter(VideoRecord.discovered_at >= today_start),
                    func.max(VideoRecord.discovered_at),
                    func.count(VideoRecord.id).filter(VideoRecord.is_excluded.is_(False)),
                    func.count(VideoRecord.id).filter(VideoRecord.is_excluded.is_(True)),
                )
            ).one()
            total = int(row[0] or 0)
            pending = int(row[1] or 0)
            today = int(row[2] or 0)
            latest_raw: datetime | None = row[3]
            latest = _ensure_utc(latest_raw) if latest_raw is not None else None
            eligible = int(row[4] or 0)
            excluded = int(row[5] or 0)
            return VideoSummary(
                total=total,
                pending=pending,
                today=today,
                latest_discovery_at=latest,
                eligible=eligible,
                excluded=excluded,
            )

    def reevaluate_exclusions(self, matcher: Callable[[str], ExclusionMatchResult]) -> int:
        """Re-classify all stored videos against updated exclusion keywords."""
        with self._sessions() as session:
            records = session.scalars(select(VideoRecord)).all()
            updated = 0
            now = utc_now()
            for record in records:
                result = matcher(record.title)
                new_json = (
                    json.dumps(result.matched_keywords, ensure_ascii=False)
                    if result.matched_keywords
                    else None
                )
                if (
                    record.is_excluded != result.excluded
                    or record.matched_exclusion_keywords != new_json
                ):
                    record.is_excluded = result.excluded
                    record.matched_exclusion_keywords = new_json
                    record.updated_at = now
                    updated += 1
            if updated:
                session.commit()
            return updated

    def update_download_state(
        self,
        video_id: int,
        *,
        download_status: DownloadStatus,
        local_video_path: str | None = None,
        actual_resolution: str | None = None,
        file_size_bytes: int | None = None,
        video_codec: str | None = None,
        download_progress: float | None = None,
        downloaded_bytes: int | None = None,
        total_bytes: int | None = None,
        download_requested: bool | None = None,
        download_started_at: datetime | None = None,
        download_completed_at: datetime | None = None,
        download_retry_count: int | None = None,
        download_error: str | None = None,
        clear_file_metadata: bool = False,
        clear_error: bool = False,
    ) -> VideoEntity | None:
        """Persist download lifecycle updates for a video."""
        with self._sessions() as session:
            record = session.get(VideoRecord, video_id)
            if record is None:
                return None

            record.download_status = download_status.value
            if clear_file_metadata:
                record.local_video_path = None
                record.actual_resolution = None
                record.file_size_bytes = None
                record.video_codec = None
                record.downloaded_bytes = 0
                record.total_bytes = None
                record.download_started_at = None
                record.download_completed_at = None
            if local_video_path is not None:
                record.local_video_path = local_video_path
            if actual_resolution is not None:
                record.actual_resolution = actual_resolution
            if file_size_bytes is not None:
                record.file_size_bytes = file_size_bytes
            if video_codec is not None:
                record.video_codec = video_codec
            if download_progress is not None:
                record.download_progress = download_progress
            if downloaded_bytes is not None:
                record.downloaded_bytes = downloaded_bytes
            if total_bytes is not None:
                record.total_bytes = total_bytes
            if download_requested is not None:
                record.download_requested = download_requested
            if download_started_at is not None:
                record.download_started_at = download_started_at
            if download_completed_at is not None:
                record.download_completed_at = download_completed_at
            if download_retry_count is not None:
                record.download_retry_count = download_retry_count
            if clear_error:
                record.download_error = None
            elif download_error is not None:
                record.download_error = download_error

            record.updated_at = utc_now()
            session.commit()
            session.refresh(record)
            return _to_entity(record)

    def list_recoverable_downloads(self) -> list[VideoEntity]:
        """Return videos that were downloading or requested before shutdown/restart."""
        with self._sessions() as session:
            bind = session.get_bind()
            if not inspect(bind).has_table("videos"):
                return []
            records = session.scalars(
                select(VideoRecord)
                .where(
                    or_(
                        VideoRecord.download_status == DownloadStatus.DOWNLOADING.value,
                        VideoRecord.download_requested.is_(True),
                    ),
                    VideoRecord.download_status != DownloadStatus.CANCELLED.value,
                    VideoRecord.download_status != DownloadStatus.DOWNLOADED.value,
                )
                .order_by(VideoRecord.id.asc())
            ).all()
            return [_to_entity(record) for record in records]

    def reset_stale_downloads(self, error_message: str) -> int:
        """Mark any leftover 'downloading' records as 'failed' after an ungraceful restart."""
        with self._sessions() as session:
            bind = session.get_bind()
            if not inspect(bind).has_table("videos"):
                return 0
            records = session.scalars(
                select(VideoRecord).where(
                    VideoRecord.download_status == DownloadStatus.DOWNLOADING.value
                )
            ).all()
            now = utc_now()
            for record in records:
                record.download_status = DownloadStatus.FAILED.value
                record.download_error = error_message
                record.updated_at = now
            if records:
                session.commit()
            return len(records)

    @staticmethod
    def _build_filters(
        *,
        search: str | None,
        channel_id: int | None,
        processing_status: ProcessingStatus | None,
        download_status: DownloadStatus | None,
        eligibility: Literal["all", "eligible", "excluded"],
        published_after: datetime | None,
        published_before: datetime | None,
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        if search is not None and search.strip():
            escaped = _escape_like(search.strip())
            pattern = f"%{escaped}%"
            filters.append(VideoRecord.title.ilike(pattern, escape="\\"))
        if channel_id is not None:
            filters.append(VideoRecord.channel_id == channel_id)
        if processing_status is not None:
            filters.append(VideoRecord.processing_status == processing_status.value)
        if download_status is not None:
            filters.append(VideoRecord.download_status == download_status.value)
        if eligibility == "eligible":
            filters.append(VideoRecord.is_excluded.is_(False))
        elif eligibility == "excluded":
            filters.append(VideoRecord.is_excluded.is_(True))
        if published_after is not None:
            filters.append(VideoRecord.published_at >= published_after)
        if published_before is not None:
            filters.append(VideoRecord.published_at <= published_before)
        return filters

    @staticmethod
    def _resolve_sort_column(sort_by: str) -> InstrumentedAttribute[Any]:
        column_map: dict[str, InstrumentedAttribute[Any]] = {
            "published_at": VideoRecord.published_at,
            "discovered_at": VideoRecord.discovered_at,
            "title": VideoRecord.title,
            "duration_seconds": VideoRecord.duration_seconds,
        }
        return column_map.get(sort_by, VideoRecord.published_at)
