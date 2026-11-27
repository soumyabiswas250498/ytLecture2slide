"""Domain contracts for automated pipeline orchestration, scheduling, and cleanup."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

PipelineTriggerType = Literal["manual", "scheduled"]
PipelineRunStatus = Literal[
    "queued",
    "running",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
]
PipelineStage = Literal[
    "idle",
    "discovering",
    "evaluating",
    "downloading",
    "extracting",
    "processing_slides",
    "generating_pdf",
    "validating_pdf",
    "cleaning",
    "completed",
]
PipelineVideoStatus = Literal[
    "pending",
    "running",
    "completed",
    "skipped",
    "excluded",
    "failed",
    "cancelled",
]

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class PipelineError(Exception):
    """Base error for pipeline orchestration and scheduling."""


class PipelineConflictError(PipelineError):
    """Raised when an overlapping run or invalid state transition is requested."""


class PipelineNotFoundError(PipelineError):
    """Raised when a requested pipeline run does not exist."""


class PipelineSettings(BaseModel):
    """Persistent operational settings for scheduling, processing, and storage."""

    model_config = ConfigDict(extra="forbid")

    scheduler_enabled: bool = True
    scheduler_frequency: Literal["daily"] = "daily"
    scheduler_time: str = "03:00"
    timezone: str = "Asia/Kolkata"
    discovery_lookback_days: int = Field(default=7, ge=1, le=30)
    extraction_interval_seconds: float = Field(default=60.0, ge=1.0, le=3600.0)
    pipeline_concurrent_limit: int = Field(default=1, ge=1, le=3)
    pipeline_retry_attempts: int = Field(default=3, ge=0, le=10)
    auto_cleanup_enabled: bool = True
    min_free_disk_mb: int = Field(default=500, ge=50, le=102400)

    @field_validator("scheduler_time")
    @classmethod
    def valid_scheduler_time(cls, value: str) -> str:
        cleaned = value.strip()
        if not _TIME_RE.match(cleaned):
            raise ValueError("scheduler_time must be in HH:MM 24-hour format (00:00–23:59)")
        return cleaned

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class PipelineRunLogEntry(BaseModel):
    """Structured execution log line stored with a pipeline run."""

    timestamp: datetime
    level: Literal["INFO", "WARNING", "ERROR"] = "INFO"
    video_id: int | None = None
    stage: str | None = None
    message: str


class PipelineRunVideoState(BaseModel):
    """Per-video execution state within a pipeline run."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    video_id: int
    video_title: str = ""
    youtube_video_id: str = ""
    status: PipelineVideoStatus = "pending"
    current_stage: PipelineStage = "idle"
    stage_progress: float = 0.0
    retry_count: int = 0
    is_retryable: bool = True
    error: str | None = None
    cleaned: bool = False
    started_at: datetime | None = None
    completed_at: datetime | None = None


class PipelineRunState(BaseModel):
    """Persistent state of a single pipeline execution run."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    trigger_type: PipelineTriggerType
    status: PipelineRunStatus
    current_stage: PipelineStage = "idle"
    current_video_id: int | None = None
    current_video_title: str | None = None
    current_stage_progress: float = 0.0
    total_videos: int = 0
    completed_videos: int = 0
    excluded_videos: int = 0
    skipped_videos: int = 0
    failed_videos: int = 0
    cancelled_videos: int = 0
    last_error: str | None = None
    reprocess_existing: bool = False
    target_video_ids: list[int] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    estimated_remaining_seconds: float | None = None
    videos: list[PipelineRunVideoState] = Field(default_factory=list)
    logs: list[PipelineRunLogEntry] = Field(default_factory=list)


class PipelineRunPage(BaseModel):
    """Paginated list of pipeline runs."""

    items: list[PipelineRunState]
    total: int
    page: int
    page_size: int
    total_pages: int


class SchedulerStatus(BaseModel):
    """Live scheduler status and next execution timestamp."""

    enabled: bool
    frequency: Literal["daily"] = "daily"
    time: str
    timezone: str
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    is_running: bool = False


class IntermediateCleanupResult(BaseModel):
    """Outcome of validating a PDF and cleaning per-video intermediate artifacts."""

    video_id: int
    cleaned: bool
    deleted_files: int = 0
    freed_bytes: int = 0
    reason: str | None = None
