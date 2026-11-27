"""SQLite repository for persistent application settings."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app.domain.exclusion import ExclusionSettings
from app.domain.pdfs import PdfCompressionMode, PdfConfig
from app.domain.pipeline import PipelineSettings
from app.infrastructure.models import AppSettingRecord, utc_now

EXCLUSION_KEYWORDS_KEY = "video_exclusion_keywords"
PDF_GENERATION_SETTINGS_KEY = "pdf_generation_settings"
PIPELINE_SETTINGS_KEY = "pipeline_settings"


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

    def get_pdf_settings(
        self, default_config: PdfConfig | None = None
    ) -> tuple[PdfConfig, datetime | None]:
        base = default_config if default_config is not None else PdfConfig()
        with self._sessions() as session:
            record = session.get(AppSettingRecord, PDF_GENERATION_SETTINGS_KEY)
            if record is None:
                return base, None
            try:
                parsed = json.loads(record.value_json)
            except json.JSONDecodeError:
                return base, _ensure_utc(record.updated_at)
            if not isinstance(parsed, dict):
                return base, _ensure_utc(record.updated_at)
            merged = base.model_dump()
            merged.update(parsed)
            try:
                return PdfConfig.model_validate(merged), _ensure_utc(record.updated_at)
            except Exception:
                return base, _ensure_utc(record.updated_at)

    def save_pdf_settings(
        self, compression: PdfCompressionMode, default_config: PdfConfig | None = None
    ) -> tuple[PdfConfig, datetime]:
        now = utc_now()
        base = default_config if default_config is not None else PdfConfig()
        config = base.model_copy(update={"compression": compression})
        payload = json.dumps({"compression": config.compression}, ensure_ascii=False)
        with self._sessions() as session:
            record = session.get(AppSettingRecord, PDF_GENERATION_SETTINGS_KEY)
            if record is None:
                record = AppSettingRecord(
                    key=PDF_GENERATION_SETTINGS_KEY,
                    value_json=payload,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.value_json = payload
                record.updated_at = now
            session.commit()
            session.refresh(record)
            updated = _ensure_utc(record.updated_at) or now
            return config, updated

    def get_pipeline_settings(
        self, default_settings: PipelineSettings | None = None
    ) -> tuple[PipelineSettings, datetime | None]:
        base = default_settings if default_settings is not None else PipelineSettings()
        with self._sessions() as session:
            record = session.get(AppSettingRecord, PIPELINE_SETTINGS_KEY)
            if record is None:
                return base, None
            try:
                parsed = json.loads(record.value_json)
            except json.JSONDecodeError:
                return base, _ensure_utc(record.updated_at)
            if not isinstance(parsed, dict):
                return base, _ensure_utc(record.updated_at)
            merged = base.model_dump()
            merged.update(parsed)
            try:
                return PipelineSettings.model_validate(merged), _ensure_utc(record.updated_at)
            except Exception:
                return base, _ensure_utc(record.updated_at)

    def save_pipeline_settings(
        self, settings_obj: PipelineSettings
    ) -> tuple[PipelineSettings, datetime]:
        now = utc_now()
        payload = settings_obj.model_dump_json()
        with self._sessions() as session:
            record = session.get(AppSettingRecord, PIPELINE_SETTINGS_KEY)
            if record is None:
                record = AppSettingRecord(
                    key=PIPELINE_SETTINGS_KEY,
                    value_json=payload,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.value_json = payload
                record.updated_at = now
            session.commit()
            session.refresh(record)
            updated = _ensure_utc(record.updated_at) or now
            return settings_obj, updated
