"""SQLite repository for persistent application settings."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app.domain.exclusion import ExclusionSettings
from app.infrastructure.models import AppSettingRecord, utc_now

EXCLUSION_KEYWORDS_KEY = "video_exclusion_keywords"


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SettingsRepository:
    """SQLAlchemy repository for typed persistent settings."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def get_exclusion_keywords(self) -> ExclusionSettings:
        with self._sessions() as session:
            record = session.get(AppSettingRecord, EXCLUSION_KEYWORDS_KEY)
            if record is None:
                return ExclusionSettings(keywords=[], updated_at=None)
            try:
                parsed = json.loads(record.value_json)
            except json.JSONDecodeError:
                parsed = []
            keywords = [str(item) for item in parsed] if isinstance(parsed, list) else []
            return ExclusionSettings(
                keywords=keywords,
                updated_at=_ensure_utc(record.updated_at),
            )

    def save_exclusion_keywords(self, keywords: list[str]) -> ExclusionSettings:
        now = utc_now()
        payload = json.dumps(keywords, ensure_ascii=False)
        with self._sessions() as session:
            record = session.get(AppSettingRecord, EXCLUSION_KEYWORDS_KEY)
            if record is None:
                record = AppSettingRecord(
                    key=EXCLUSION_KEYWORDS_KEY,
                    value_json=payload,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.value_json = payload
                record.updated_at = now
            session.commit()
            session.refresh(record)
            return ExclusionSettings(
                keywords=list(keywords),
                updated_at=_ensure_utc(record.updated_at),
            )
