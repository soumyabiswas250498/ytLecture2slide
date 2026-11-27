"""FastAPI routes for automated pipeline runs, scheduling, and intermediate cleanup."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from app.domain.pipeline import (
    IntermediateCleanupResult,
    PipelineRunPage,
    PipelineRunState,
    SchedulerStatus,
)
from app.services.pipeline import PipelineOrchestrator
from app.services.pipeline_cleanup import PipelineCleanupService
from app.services.scheduler import PipelineSchedulerService

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


def _get_orchestrator(request: Request) -> PipelineOrchestrator:
    orchestrator: PipelineOrchestrator = request.app.state.pipeline_orchestrator
    return orchestrator


def _get_scheduler(request: Request) -> PipelineSchedulerService:
    scheduler: PipelineSchedulerService = request.app.state.scheduler_service
    return scheduler


def _get_cleanup(request: Request) -> PipelineCleanupService:
    cleanup: PipelineCleanupService = request.app.state.pipeline_cleanup_service
    return cleanup


OrchestratorDep = Annotated[PipelineOrchestrator, Depends(_get_orchestrator)]
SchedulerDep = Annotated[PipelineSchedulerService, Depends(_get_scheduler)]
CleanupDep = Annotated[PipelineCleanupService, Depends(_get_cleanup)]


class PipelineRunTriggerRequest(BaseModel):
    video_ids: list[int] | None = Field(default=None, max_length=200)
    reprocess_existing: bool = False


@router.get("/scheduler", response_model=SchedulerStatus)
def get_scheduler_status(scheduler: SchedulerDep) -> SchedulerStatus:
    return scheduler.get_status()


@router.get("/runs", response_model=PipelineRunPage)
def list_pipeline_runs(
    orchestrator: OrchestratorDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PipelineRunPage:
    return orchestrator.list_runs(page=page, page_size=page_size)


@router.get("/runs/active", response_model=PipelineRunState | None)
def get_active_pipeline_run(orchestrator: OrchestratorDep) -> PipelineRunState | None:
    return orchestrator.get_active_run()


@router.get("/runs/{run_id}", response_model=PipelineRunState)
def get_pipeline_run(run_id: int, orchestrator: OrchestratorDep) -> PipelineRunState:
    return orchestrator.get_run(run_id)


@router.post("/runs", response_model=PipelineRunState, status_code=status.HTTP_202_ACCEPTED)
def trigger_pipeline_run(
    payload: PipelineRunTriggerRequest,
    orchestrator: OrchestratorDep,
) -> PipelineRunState:
    return orchestrator.trigger_run(
        "manual",
        video_ids=payload.video_ids,
        reprocess_existing=payload.reprocess_existing,
    )


@router.post("/runs/{run_id}/cancel", response_model=PipelineRunState)
def cancel_pipeline_run(run_id: int, orchestrator: OrchestratorDep) -> PipelineRunState:
    return orchestrator.cancel_run(run_id)


@router.post(
    "/runs/{run_id}/retry-failed",
    response_model=PipelineRunState,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_failed_pipeline_run(run_id: int, orchestrator: OrchestratorDep) -> PipelineRunState:
    return orchestrator.retry_failed_run(run_id)


@router.post("/videos/{video_id}/cleanup", response_model=IntermediateCleanupResult)
def cleanup_video_intermediates(video_id: int, cleanup: CleanupDep) -> IntermediateCleanupResult:
    return cleanup.cleanup_video_intermediates(video_id)
