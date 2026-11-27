"""Transactional slide claims and independent durable state."""

import json
from typing import Any

from sqlalchemy import inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.slides import ChannelBoardProfile, Crop, SlideConfig, SlideConflict, SlideState
from app.infrastructure.models import ChannelBoardProfileRecord, SlideProcessingRecord, utc_now


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


class ChannelBoardProfileRepository:
    """SQLite persistence for per-channel smartboard crop and perspective profiles."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    @staticmethod
    def _to_domain(record: ChannelBoardProfileRecord) -> ChannelBoardProfile:
        corners = json.loads(record.corners_json) if record.corners_json else None
        return ChannelBoardProfile(
            channel_id=record.channel_id,
            crop=Crop(
                left=record.crop_left,
                top=record.crop_top,
                right=record.crop_right,
                bottom=record.crop_bottom,
            ),
            corners=[tuple(pt) for pt in corners] if corners else None,
            reference_width=record.reference_width,
            reference_height=record.reference_height,
            validated=record.validated,
            updated_at=record.updated_at,
        )

    def get(self, channel_id: int) -> ChannelBoardProfile | None:
        with self._sessions() as session:
            if not inspect(session.get_bind()).has_table("channel_board_profiles"):
                return None
            row = session.get(ChannelBoardProfileRecord, channel_id)
            return self._to_domain(row) if row else None

    def upsert(self, profile: ChannelBoardProfile) -> ChannelBoardProfile:
        now = utc_now()
        corners_json = json.dumps(profile.corners) if profile.corners else None
        with self._sessions() as session:
            row = session.get(ChannelBoardProfileRecord, profile.channel_id)
            if row is None:
                row = ChannelBoardProfileRecord(channel_id=profile.channel_id)
                session.add(row)
            row.crop_left = profile.crop.left
            row.crop_top = profile.crop.top
            row.crop_right = profile.crop.right
            row.crop_bottom = profile.crop.bottom
            row.corners_json = corners_json
            row.reference_width = profile.reference_width
            row.reference_height = profile.reference_height
            row.validated = profile.validated
            row.updated_at = now
            session.commit()
            session.refresh(row)
            return self._to_domain(row)

    def delete(self, channel_id: int) -> bool:
        with self._sessions() as session:
            row = session.get(ChannelBoardProfileRecord, channel_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True
