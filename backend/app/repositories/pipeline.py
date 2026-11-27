"""SQLite repository for pipeline runs, per-video state, and execution logs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from math import ceil
from typing import Any, Literal, cast

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.pipeline import (
    PipelineConflictError,
    PipelineNotFoundError,
    PipelineRunLogEntry,
    PipelineRunPage,
    PipelineRunState,
    PipelineRunStatus,
    PipelineRunVideoState,
    PipelineStage,
    PipelineTriggerType,
    PipelineVideoStatus,
)
from app.infrastructure.models import PipelineRunRecord, PipelineRunVideoRecord, utc_now

_ACTIVE_RUN_STATUSES = ("queued", "running")
_MAX_STORED_LOGS = 500
_UNSET: Any = object()


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_int_list(raw: str) -> list[int]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    result: list[int] = []
    for item in parsed:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _parse_logs(raw: str) -> list[PipelineRunLogEntry]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    entries: list[PipelineRunLogEntry] = []
    for item in parsed:
        if isinstance(item, dict):
            try:
                entries.append(PipelineRunLogEntry.model_validate(item))
            except Exception:
                continue
    return entries


def _estimate_remaining_seconds(
    record: PipelineRunRecord, videos: list[PipelineRunVideoState]
) -> float | None:
    if record.status not in _ACTIVE_RUN_STATUSES:
        return 0.0
    completed_durations = [
        (v.completed_at - v.started_at).total_seconds()
        for v in videos
        if v.status == "completed" and v.started_at is not None and v.completed_at is not None
    ]
    if not completed_durations:
        return None
    remaining_count = sum(1 for v in videos if v.status in {"pending", "running"})
    if remaining_count <= 0:
        return 0.0
    avg_seconds = sum(completed_durations) / len(completed_durations)
    return round(avg_seconds * remaining_count, 1)


def _video_to_domain(record: PipelineRunVideoRecord) -> PipelineRunVideoState:
    return PipelineRunVideoState(
        id=record.id,
        run_id=record.run_id,
        video_id=record.video_id,
        video_title=record.video_title,
        youtube_video_id=record.youtube_video_id,
        status=cast(PipelineVideoStatus, record.status),
        current_stage=cast(PipelineStage, record.current_stage),
        stage_progress=record.stage_progress,
        retry_count=record.retry_count,
        is_retryable=record.is_retryable,
        error=record.error,
        cleaned=record.cleaned,
        started_at=_ensure_utc(record.started_at),
        completed_at=_ensure_utc(record.completed_at),
    )


def _run_to_domain(
    record: PipelineRunRecord, videos: list[PipelineRunVideoState] | None = None
) -> PipelineRunState:
    video_list = videos if videos is not None else []
    return PipelineRunState(
        id=record.id,
        trigger_type=cast(PipelineTriggerType, record.trigger_type),
        status=cast(PipelineRunStatus, record.status),
        current_stage=cast(PipelineStage, record.current_stage),
        current_video_id=record.current_video_id,
        current_video_title=record.current_video_title,
        current_stage_progress=record.current_stage_progress,
        total_videos=record.total_videos,
        completed_videos=record.completed_videos,
        excluded_videos=record.excluded_videos,
        skipped_videos=record.skipped_videos,
        failed_videos=record.failed_videos,
        cancelled_videos=record.cancelled_videos,
        last_error=record.last_error,
        reprocess_existing=record.reprocess_existing,
        target_video_ids=_parse_int_list(record.target_video_ids_json),
        started_at=_ensure_utc(record.started_at),
        completed_at=_ensure_utc(record.completed_at),
        created_at=_ensure_utc(record.created_at) or utc_now(),
        updated_at=_ensure_utc(record.updated_at) or utc_now(),
        estimated_remaining_seconds=_estimate_remaining_seconds(record, video_list),
        videos=video_list,
        logs=_parse_logs(record.logs_json),
    )


class PipelineRepository:
    """SQLAlchemy repository for durable pipeline runs and per-video execution state."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create_run(
        self,
        *,
        trigger_type: PipelineTriggerType,
        reprocess_existing: bool = False,
        target_video_ids: list[int] | None = None,
    ) -> PipelineRunState:
        now = utc_now()
        targets = list(dict.fromkeys(target_video_ids or []))
        with self._sessions() as session:
            active = session.scalar(
                select(PipelineRunRecord).where(PipelineRunRecord.status.in_(_ACTIVE_RUN_STATUSES))
            )
            if active is not None:
                raise PipelineConflictError(
                    f"Pipeline run #{active.id} is already {active.status}."
                )
            record = PipelineRunRecord(
                trigger_type=trigger_type,
                status="queued",
                current_stage="idle",
                reprocess_existing=reprocess_existing,
                target_video_ids_json=json.dumps(targets),
                logs_json="[]",
                started_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return _run_to_domain(record, [])

    def get_run(self, run_id: int, *, include_videos: bool = True) -> PipelineRunState:
        with self._sessions() as session:
            record = session.get(PipelineRunRecord, run_id)
            if record is None:
                raise PipelineNotFoundError(f"Pipeline run #{run_id} not found.")
            videos: list[PipelineRunVideoState] = []
            if include_videos:
                rows = session.scalars(
                    select(PipelineRunVideoRecord)
                    .where(PipelineRunVideoRecord.run_id == run_id)
                    .order_by(PipelineRunVideoRecord.id.asc())
                ).all()
                videos = [_video_to_domain(row) for row in rows]
            return _run_to_domain(record, videos)

    def get_active_run(self) -> PipelineRunState | None:
        with self._sessions() as session:
            if not inspect(session.get_bind()).has_table("pipeline_runs"):
                return None
            record = session.scalar(
                select(PipelineRunRecord)
                .where(PipelineRunRecord.status.in_(_ACTIVE_RUN_STATUSES))
                .order_by(PipelineRunRecord.id.desc())
            )
            if record is None:
                return None
            rows = session.scalars(
                select(PipelineRunVideoRecord)
                .where(PipelineRunVideoRecord.run_id == record.id)
                .order_by(PipelineRunVideoRecord.id.asc())
            ).all()
            return _run_to_domain(record, [_video_to_domain(row) for row in rows])

    def get_latest_scheduled_run(self) -> PipelineRunState | None:
        with self._sessions() as session:
            if not inspect(session.get_bind()).has_table("pipeline_runs"):
                return None
            record = session.scalar(
                select(PipelineRunRecord)
                .where(PipelineRunRecord.trigger_type == "scheduled")
                .order_by(PipelineRunRecord.id.desc())
            )
            if record is None:
                return None
            return _run_to_domain(record, [])

    def list_runs(self, *, page: int = 1, page_size: int = 20) -> PipelineRunPage:
        with self._sessions() as session:
            total = session.scalar(select(func.count()).select_from(PipelineRunRecord)) or 0
            offset = (page - 1) * page_size
            records = session.scalars(
                select(PipelineRunRecord)
                .order_by(PipelineRunRecord.id.desc())
                .offset(offset)
                .limit(page_size)
            ).all()
            items: list[PipelineRunState] = []
            for record in records:
                rows = session.scalars(
                    select(PipelineRunVideoRecord)
                    .where(PipelineRunVideoRecord.run_id == record.id)
                    .order_by(PipelineRunVideoRecord.id.asc())
                ).all()
                items.append(_run_to_domain(record, [_video_to_domain(r) for r in rows]))
            total_pages = max(1, ceil(total / page_size)) if total > 0 else 1
            return PipelineRunPage(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
            )

    def update_run(self, run_id: int, **values: Any) -> PipelineRunState:
        with self._sessions() as session:
            record = session.get(PipelineRunRecord, run_id)
            if record is None:
                raise PipelineNotFoundError(f"Pipeline run #{run_id} not found.")
            for key, value in values.items():
                setattr(record, key, value)
            record.updated_at = utc_now()
            session.commit()
            session.refresh(record)
            rows = session.scalars(
                select(PipelineRunVideoRecord)
                .where(PipelineRunVideoRecord.run_id == run_id)
                .order_by(PipelineRunVideoRecord.id.asc())
            ).all()
            return _run_to_domain(record, [_video_to_domain(r) for r in rows])

    def append_log(
        self,
        run_id: int,
        message: str,
        *,
        level: Literal["INFO", "WARNING", "ERROR"] = "INFO",
        video_id: int | None = None,
        stage: str | None = None,
    ) -> None:
        entry = PipelineRunLogEntry(
            timestamp=utc_now(),
            level=level,
            video_id=video_id,
            stage=stage,
            message=message,
        )
        with self._sessions() as session:
            record = session.get(PipelineRunRecord, run_id)
            if record is None:
                return
            logs = _parse_logs(record.logs_json)
            logs.append(entry)
            if len(logs) > _MAX_STORED_LOGS:
                logs = logs[-_MAX_STORED_LOGS:]
            record.logs_json = json.dumps([item.model_dump(mode="json") for item in logs])
            record.updated_at = utc_now()
            session.commit()

    def ensure_run_video(
        self,
        run_id: int,
        *,
        video_id: int,
        video_title: str,
        youtube_video_id: str,
        status: PipelineVideoStatus = "pending",
    ) -> PipelineRunVideoState:
        with self._sessions() as session:
            row = session.scalar(
                select(PipelineRunVideoRecord).where(
                    PipelineRunVideoRecord.run_id == run_id,
                    PipelineRunVideoRecord.video_id == video_id,
                )
            )
            if row is None:
                row = PipelineRunVideoRecord(
                    run_id=run_id,
                    video_id=video_id,
                    video_title=video_title,
                    youtube_video_id=youtube_video_id,
                    status=status,
                    current_stage="idle",
                )
                session.add(row)
                session.commit()
                session.refresh(row)
            return _video_to_domain(row)

    def get_run_videos(self, run_id: int) -> list[PipelineRunVideoState]:
        with self._sessions() as session:
            rows = session.scalars(
                select(PipelineRunVideoRecord)
                .where(PipelineRunVideoRecord.run_id == run_id)
                .order_by(PipelineRunVideoRecord.id.asc())
            ).all()
            return [_video_to_domain(r) for r in rows]

    def update_run_video(
        self,
        run_id: int,
        video_id: int,
        *,
        status: PipelineVideoStatus | None = None,
        current_stage: PipelineStage | None = None,
        stage_progress: float | None = None,
        retry_count: int | None = None,
        is_retryable: bool | None = None,
        error: Any = _UNSET,
        cleaned: bool | None = None,
        started_at: Any = _UNSET,
        completed_at: Any = _UNSET,
    ) -> PipelineRunVideoState | None:
        with self._sessions() as session:
            row = session.scalar(
                select(PipelineRunVideoRecord).where(
                    PipelineRunVideoRecord.run_id == run_id,
                    PipelineRunVideoRecord.video_id == video_id,
                )
            )
            if row is None:
                return None
            if status is not None:
                row.status = status
            if current_stage is not None:
                row.current_stage = current_stage
            if stage_progress is not None:
                row.stage_progress = stage_progress
            if retry_count is not None:
                row.retry_count = retry_count
            if is_retryable is not None:
                row.is_retryable = is_retryable
            if error is not _UNSET:
                row.error = error
            if cleaned is not None:
                row.cleaned = cleaned
            if started_at is not _UNSET:
                row.started_at = started_at
            if completed_at is not _UNSET:
                row.completed_at = completed_at
            session.commit()
            session.refresh(row)
            return _video_to_domain(row)

    def sync_run_counts(self, run_id: int) -> PipelineRunState:
        with self._sessions() as session:
            record = session.get(PipelineRunRecord, run_id)
            if record is None:
                raise PipelineNotFoundError(f"Pipeline run #{run_id} not found.")
            rows = session.scalars(
                select(PipelineRunVideoRecord).where(PipelineRunVideoRecord.run_id == run_id)
            ).all()
            record.completed_videos = sum(1 for r in rows if r.status == "completed")
            record.excluded_videos = sum(1 for r in rows if r.status == "excluded")
            record.skipped_videos = sum(1 for r in rows if r.status == "skipped")
            record.failed_videos = sum(1 for r in rows if r.status == "failed")
            record.cancelled_videos = sum(1 for r in rows if r.status == "cancelled")
            record.total_videos = sum(1 for r in rows if r.status not in {"excluded", "skipped"})
            record.updated_at = utc_now()
            session.commit()
            session.refresh(record)
            return _run_to_domain(record, [_video_to_domain(r) for r in rows])

    def list_recoverable_runs(self) -> list[PipelineRunState]:
        with self._sessions() as session:
            if not inspect(session.get_bind()).has_table("pipeline_runs"):
                return []
            records = session.scalars(
                select(PipelineRunRecord)
                .where(PipelineRunRecord.status.in_(_ACTIVE_RUN_STATUSES))
                .order_by(PipelineRunRecord.id.asc())
            ).all()
            return [_run_to_domain(r, []) for r in records]
