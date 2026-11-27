"""Persistence and atomic claims for extraction jobs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.extraction import ExtractionConflict, ExtractionStatus
from app.infrastructure.models import ExtractionRecord


class ExtractionState(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    video_id: int
    status: ExtractionStatus = ExtractionStatus.PENDING
    progress: float = 0
    requested: bool = False
    interval_seconds: float = 60
    frame_count: int = 0
    expected_count: int | None = None
    frame_directory: str | None = None
    manifest_path: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0
    error: str | None = None


class ExtractionRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def cleanup_state(self, video_id: int) -> ExtractionState:
        with self._sessions() as session:
            if not inspect(session.get_bind()).has_table("extractions"):
                return ExtractionState(video_id=video_id)
        return self.get(video_id)

    def get(self, video_id: int) -> ExtractionState:
        with self._sessions() as session:
            row = session.get(ExtractionRecord, video_id)
            return (
                ExtractionState.model_validate(row) if row else ExtractionState(video_id=video_id)
            )

    def save(self, video_id: int, **values: Any) -> ExtractionState:
        with self._sessions() as session:
            row = session.get(ExtractionRecord, video_id)
            if row is None:
                row = ExtractionRecord(video_id=video_id)
                session.add(row)
            for key, value in values.items():
                setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return ExtractionState.model_validate(row)

    def claim(self, video_id: int, interval: float) -> ExtractionState:
        try:
            return self._claim(video_id, interval)
        except IntegrityError as exc:
            raise ExtractionConflict("Another request claimed this extraction.") from exc

    def _claim(self, video_id: int, interval: float) -> ExtractionState:
        with self._sessions() as session:
            row = session.get(ExtractionRecord, video_id)
            if row is None:
                row = ExtractionRecord(video_id=video_id)
                session.add(row)
                session.flush()
            changed = session.execute(
                update(ExtractionRecord)
                .where(
                    ExtractionRecord.video_id == video_id,
                    ExtractionRecord.requested.is_(False),
                    ExtractionRecord.status != "extracting",
                )
                .values(
                    requested=True,
                    status="pending",
                    interval_seconds=interval,
                    progress=0,
                    frame_count=0,
                    expected_count=None,
                    error=None,
                    retry_count=0,
                    started_at=None,
                    completed_at=None,
                )
            )
            if changed.rowcount != 1:  # type: ignore[attr-defined]
                raise ExtractionConflict("Extraction is already queued or running.")
            session.commit()
        return self.get(video_id)

    def recoverable(self) -> list[ExtractionState]:
        with self._sessions() as session:
            if not inspect(session.get_bind()).has_table("extractions"):
                return []
            rows = session.scalars(
                select(ExtractionRecord).where(
                    ExtractionRecord.requested.is_(True),
                    ExtractionRecord.status != "cancelled",
                )
            ).all()
            return [ExtractionState.model_validate(row) for row in rows]
