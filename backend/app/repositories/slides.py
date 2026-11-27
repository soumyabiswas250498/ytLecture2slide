"""Transactional slide claims and independent durable state."""

from typing import Any

from sqlalchemy import inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.slides import SlideConfig, SlideConflict, SlideState
from app.infrastructure.models import SlideProcessingRecord


class SlideRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def get(self, video_id: int) -> SlideState:
        with self.sessions() as session:
            row = session.get(SlideProcessingRecord, video_id)
            return SlideState.model_validate(row) if row else SlideState(video_id=video_id)

    def save(self, video_id: int, **values: Any) -> SlideState:
        with self.sessions() as session:
            row = session.get(SlideProcessingRecord, video_id)
            if row is None:
                row = SlideProcessingRecord(video_id=video_id)
                session.add(row)
            for key, value in values.items():
                setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return SlideState.model_validate(row)

    def claim(self, video_id: int, configuration: SlideConfig) -> SlideState:
        try:
            with self.sessions() as session:
                if session.get(SlideProcessingRecord, video_id) is None:
                    session.add(SlideProcessingRecord(video_id=video_id))
                    session.flush()
                changed = session.execute(
                    update(SlideProcessingRecord)
                    .where(
                        SlideProcessingRecord.video_id == video_id,
                        SlideProcessingRecord.requested.is_(False),
                        SlideProcessingRecord.status != "processing",
                    )
                    .values(
                        requested=True,
                        status="pending",
                        progress=0,
                        completed_count=0,
                        additional_count=0,
                        error=None,
                        retry_count=0,
                        configuration=configuration.model_dump_json(),
                    )
                )
                if changed.rowcount != 1:  # type: ignore[attr-defined]
                    raise SlideConflict("Slide processing is already requested.")
                session.commit()
        except IntegrityError as exc:
            raise SlideConflict("Another request claimed slide processing.") from exc
        return self.get(video_id)

    def recoverable(self) -> list[SlideState]:
        with self.sessions() as session:
            if not inspect(session.get_bind()).has_table("slide_processing"):
                return []
            return [
                SlideState.model_validate(row)
                for row in session.scalars(
                    select(SlideProcessingRecord).where(SlideProcessingRecord.requested.is_(True))
                )
            ]
