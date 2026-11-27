"""FastAPI routes for persistent application settings."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.domain.exclusion import DEFAULT_SUGGESTED_KEYWORDS
from app.domain.pdfs import (
    COMPRESSION_MODE_DESCRIPTIONS,
    PdfCompressionMode,
    PdfConfig,
)
from app.domain.pipeline import PipelineSettings
from app.repositories.settings import SettingsRepository
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


class PdfCompressionOption(BaseModel):
    mode: PdfCompressionMode
    label: str
    description: str


PDF_COMPRESSION_OPTIONS: list[PdfCompressionOption] = [
    PdfCompressionOption(
        mode="lossless",
        label="Lossless (Original PNG)",
        description=COMPRESSION_MODE_DESCRIPTIONS["lossless"],
    ),
    PdfCompressionOption(
        mode="maximum_quality",
        label="Maximum quality (JPEG 95)",
        description=COMPRESSION_MODE_DESCRIPTIONS["maximum_quality"],
    ),
    PdfCompressionOption(
        mode="high_quality",
        label="High quality (JPEG 90)",
        description=COMPRESSION_MODE_DESCRIPTIONS["high_quality"],
    ),
    PdfCompressionOption(
        mode="compact",
        label="Compact (JPEG 85)",
        description=COMPRESSION_MODE_DESCRIPTIONS["compact"],
    ),
]


class PdfSettingsResponse(BaseModel):
    compression: PdfCompressionMode
    default_compression: PdfCompressionMode
    options: list[PdfCompressionOption]
    updated_at: datetime | None = None


class PdfSettingsUpdateRequest(BaseModel):
    compression: PdfCompressionMode


def _get_settings_repo(request: Request) -> SettingsRepository:
    return SettingsRepository(request.app.state.sessions)


SettingsRepoDep = Annotated[SettingsRepository, Depends(_get_settings_repo)]


@router.get("/pdf", response_model=PdfSettingsResponse)
def get_pdf_settings(
    request: Request,
    repo: SettingsRepoDep,
) -> PdfSettingsResponse:
    default_cfg: PdfConfig = request.app.state.settings.pdf_generation
    cfg, updated_at = repo.get_pdf_settings(default_cfg)
    return PdfSettingsResponse(
        compression=cfg.compression,
        default_compression=default_cfg.compression,
        options=PDF_COMPRESSION_OPTIONS,
        updated_at=updated_at,
    )


@router.put("/pdf", response_model=PdfSettingsResponse)
def update_pdf_settings(
    payload: PdfSettingsUpdateRequest,
    request: Request,
    repo: SettingsRepoDep,
) -> PdfSettingsResponse:
    default_cfg: PdfConfig = request.app.state.settings.pdf_generation
    cfg, updated_at = repo.save_pdf_settings(payload.compression, default_cfg)
    return PdfSettingsResponse(
        compression=cfg.compression,
        default_compression=default_cfg.compression,
        options=PDF_COMPRESSION_OPTIONS,
        updated_at=updated_at,
    )


class PipelineSettingsResponse(PipelineSettings):
    updated_at: datetime | None = None


@router.get("/pipeline", response_model=PipelineSettingsResponse)
def get_pipeline_settings(
    request: Request,
    repo: SettingsRepoDep,
) -> PipelineSettingsResponse:
    orchestrator = request.app.state.pipeline_orchestrator
    defaults: PipelineSettings = orchestrator.default_pipeline_settings()
    cfg, updated_at = repo.get_pipeline_settings(defaults)
    return PipelineSettingsResponse(**cfg.model_dump(), updated_at=updated_at)


@router.put("/pipeline", response_model=PipelineSettingsResponse)
def update_pipeline_settings(
    payload: PipelineSettings,
    request: Request,
    repo: SettingsRepoDep,
) -> PipelineSettingsResponse:
    saved, updated_at = repo.save_pipeline_settings(payload)
    scheduler = getattr(request.app.state, "scheduler_service", None)
    if scheduler is not None:
        scheduler.sync_schedule(saved)
    return PipelineSettingsResponse(**saved.model_dump(), updated_at=updated_at)
