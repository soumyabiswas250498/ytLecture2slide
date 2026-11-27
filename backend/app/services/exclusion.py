"""Application service for configurable video exclusion keywords and eligibility."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.exclusion import (
    ExclusionMatchResult,
    ExclusionSettings,
    VideoExcludedError,
    deduplicate_keywords,
    format_exclusion_reason,
    match_title,
)
from app.repositories.settings import SettingsRepository
from app.repositories.videos import VideoRepository


@dataclass(frozen=True)
class ExclusionUpdateResult:
    settings: ExclusionSettings
    reevaluated_count: int
    excluded_video_count: int
    eligible_video_count: int


class VideoExclusionService:
    """Centralized service for exclusion keyword management, matching, and video reevaluation."""

    def __init__(
        self,
        *,
        settings_repo: SettingsRepository,
        video_repo: VideoRepository,
        lock: threading.RLock | None = None,
    ) -> None:
        self._settings_repo = settings_repo
        self._video_repo = video_repo
        self._lock = lock or threading.RLock()

    def get_settings(self) -> ExclusionSettings:
        return self._settings_repo.get_exclusion_keywords()

    def update_keywords(
        self, keywords: Sequence[str], *, reject_duplicates: bool = True
    ) -> ExclusionUpdateResult:
        cleaned = deduplicate_keywords(keywords, reject_duplicates=reject_duplicates)
        with self._lock:
            saved = self._settings_repo.save_exclusion_keywords(cleaned)
            reevaluated = self._video_repo.reevaluate_exclusions(
                lambda title: match_title(title, saved.keywords)
            )
            summary = self._video_repo.get_summary()
            return ExclusionUpdateResult(
                settings=saved,
                reevaluated_count=reevaluated,
                excluded_video_count=summary.excluded,
                eligible_video_count=summary.eligible,
            )

    def classify_title(self, title: str) -> ExclusionMatchResult:
        settings = self._settings_repo.get_exclusion_keywords()
        return match_title(title, settings.keywords)

    def assert_video_eligible(self, video_id: int) -> None:
        video = self._video_repo.get_by_id(video_id)
        if video is not None and video.is_excluded:
            raise VideoExcludedError(
                format_exclusion_reason(video.excluded_keywords),
                video.excluded_keywords,
            )
