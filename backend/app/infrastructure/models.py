from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ChannelRecord(Base):
    __tablename__ = "channels"
    __table_args__ = (
        Index("ix_channels_name", "name"),
        Index("ix_channels_is_active", "is_active"),
        Index("ix_channels_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_url: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    sample_video_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    search_keyword: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class VideoRecord(Base):
    __tablename__ = "videos"
    __table_args__ = (
        UniqueConstraint("youtube_video_id", name="uq_videos_youtube_video_id"),
        Index("ix_videos_channel_id", "channel_id"),
        Index("ix_videos_published_at", "published_at"),
        Index("ix_videos_processing_status", "processing_status"),
        Index("ix_videos_download_status", "download_status"),
        Index("ix_videos_discovered_at", "discovered_at"),
        Index("ix_videos_is_excluded", "is_excluded"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Nullable FK — channel deletion must NOT cascade-delete video processing history.
    channel_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    youtube_channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    youtube_video_id: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    video_url: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    livestream_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    download_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    local_video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    actual_resolution: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_codec: Mapped[str | None] = mapped_column(String(64), nullable=True)
    download_progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    downloaded_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    download_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    download_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    download_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    download_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    download_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    matched_exclusion_keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ExtractionRecord(Base):
    __tablename__ = "extractions"

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    interval_seconds: Mapped[float] = mapped_column(Float, default=60, nullable=False)
    frame_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expected_count: Mapped[int | None] = mapped_column(Integer)
    frame_directory: Mapped[str | None] = mapped_column(String(1024))
    manifest_path: Mapped[str | None] = mapped_column(String(1024))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class SlideProcessingRecord(Base):
    __tablename__ = "slide_processing"

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    input_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    additional_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reconstructed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    configuration: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    output_directory: Mapped[str | None] = mapped_column(String(1024))
    error: Mapped[str | None] = mapped_column(Text)


class ChannelBoardProfileRecord(Base):
    __tablename__ = "channel_board_profiles"

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True
    )
    crop_left: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    crop_top: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    crop_right: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    crop_bottom: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    corners_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AppSettingRecord(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class PdfGenerationRecord(Base):
    __tablename__ = "pdf_generations"
    __table_args__ = (
        Index("ix_pdf_generations_status", "status"),
        Index("ix_pdf_generations_completed_at", "completed_at"),
    )

    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), primary_key=True)
    source_slide_generation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    completed_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    pdf_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    configuration: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
