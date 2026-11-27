"""FastAPI routes for persistent application settings."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.domain.exclusion import DEFAULT_SUGGESTED_KEYWORDS
from app.services.exclusion import VideoExclusionService

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def _get_exclusion_service(request: Request) -> VideoExclusionService:
    service: VideoExclusionService = request.app.state.exclusion_service
    return service


ExclusionServiceDep = Annotated[VideoExclusionService, Depends(_get_exclusion_service)]


class ExclusionKeywordsResponse(BaseModel):
    keywords: list[str]
    suggested_keywords: list[str]
    updated_at: datetime | None = None
    reevaluated_count: int = 0
    excluded_video_count: int = 0
    eligible_video_count: int = 0


class ExclusionKeywordsUpdateRequest(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=200)


@router.get("/exclusion-keywords", response_model=ExclusionKeywordsResponse)
def get_exclusion_keywords(
    request: Request,
    service: ExclusionServiceDep,
) -> ExclusionKeywordsResponse:
    settings = service.get_settings()
    summary = service._video_repo.get_summary()  # noqa: SLF001
    return ExclusionKeywordsResponse(
        keywords=settings.keywords,
        suggested_keywords=list(DEFAULT_SUGGESTED_KEYWORDS),
        updated_at=settings.updated_at,
        excluded_video_count=summary.excluded,
        eligible_video_count=summary.eligible,
    )


@router.put("/exclusion-keywords", response_model=ExclusionKeywordsResponse)
def update_exclusion_keywords(
    payload: ExclusionKeywordsUpdateRequest,
    service: ExclusionServiceDep,
) -> ExclusionKeywordsResponse:
    result = service.update_keywords(payload.keywords, reject_duplicates=True)
    return ExclusionKeywordsResponse(
        keywords=result.settings.keywords,
        suggested_keywords=list(DEFAULT_SUGGESTED_KEYWORDS),
        updated_at=result.settings.updated_at,
        reevaluated_count=result.reevaluated_count,
        excluded_video_count=result.excluded_video_count,
        eligible_video_count=result.eligible_video_count,
    )
