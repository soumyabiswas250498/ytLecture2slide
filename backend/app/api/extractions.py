"""HTTP boundary for background extraction and paginated frame previews."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.domain.downloads import VideoNotFoundError
from app.domain.exclusion import VideoExcludedError
from app.domain.extraction import ExtractionError, FrameMetadata
from app.infrastructure.frame_extractor import read_manifest, validate_png
from app.repositories.extractions import ExtractionState
from app.services.extraction import ExtractionService

router = APIRouter(prefix="/api/v1/videos", tags=["frames"])


def service(request: Request) -> ExtractionService:
    result: ExtractionService = request.app.state.extraction_service
    return result


Service = Annotated[ExtractionService, Depends(service)]


class ExtractionRequest(BaseModel):
    interval_seconds: float | None = Field(default=None, ge=0.001, allow_inf_nan=False)


class BulkRequest(ExtractionRequest):
    video_ids: list[int] = Field(min_length=1, max_length=100)


class BulkOutcome(BaseModel):
    video_id: int
    reason: str


class BulkResult(BaseModel):
    started_ids: list[int] = []
    errors: list[BulkOutcome] = []


class FramePage(BaseModel):
    items: list[FrameMetadata]
    total: int
    page: int
    page_size: int
    video_duration: float


@router.get("/extractions/config")
def extraction_config(request: Request) -> dict[str, float]:
    return {"interval_seconds": request.app.state.settings.extraction_interval_seconds}


@router.post("/extractions/bulk", status_code=202)
def bulk(payload: BulkRequest, jobs: Service) -> BulkResult:
    result = BulkResult()
    for video_id in dict.fromkeys(payload.video_ids):
        try:
            jobs.start(video_id, payload.interval_seconds)
            result.started_ids.append(video_id)
        except (ExtractionError, VideoNotFoundError, VideoExcludedError) as exc:
            result.errors.append(BulkOutcome(video_id=video_id, reason=str(exc)))
    return result


@router.post("/{video_id}/extraction", status_code=202)
def start(video_id: int, payload: ExtractionRequest, jobs: Service) -> ExtractionState:
    return jobs.start(video_id, payload.interval_seconds)


@router.get("/{video_id}/extraction")
def progress(video_id: int, jobs: Service) -> ExtractionState:
    return jobs.state(video_id)


@router.post("/{video_id}/extraction/cancel")
def cancel(video_id: int, jobs: Service) -> ExtractionState:
    return jobs.cancel(video_id)


@router.post("/{video_id}/extraction/retry", status_code=202)
def retry(video_id: int, jobs: Service) -> ExtractionState:
    return jobs.start(video_id, retry=True)


@router.delete("/{video_id}/extraction")
def delete(video_id: int, jobs: Service) -> ExtractionState:
    return jobs.delete(video_id)


@router.get("/{video_id}/frames")
def frames(
    video_id: int,
    jobs: Service,
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=48),
) -> FramePage:
    result = read_manifest(jobs.directory(video_id), validate_images=False)
    offset = (page - 1) * page_size
    return FramePage(
        items=result.frames[offset : offset + page_size],
        total=result.frame_count,
        page=page,
        page_size=page_size,
        video_duration=result.video_duration,
    )


@router.get("/{video_id}/frames/{filename}")
def preview(video_id: int, filename: str, jobs: Service) -> FileResponse:
    directory = jobs.directory(video_id)
    result = read_manifest(directory, validate_images=False)
    if filename not in {frame.filename for frame in result.frames}:
        raise HTTPException(404, "Frame not found.")
    selected = next(frame for frame in result.frames if frame.filename == filename)
    validate_png(directory / filename, selected.width, selected.height)
    return FileResponse(
        directory / filename, media_type="image/png", headers={"Cache-Control": "private, no-cache"}
    )
