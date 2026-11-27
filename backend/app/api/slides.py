"""HTTP boundary for slide jobs and generation-consistent comparison previews."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.domain.downloads import VideoNotFoundError
from app.domain.exclusion import VideoExcludedError
from app.domain.extraction import ExtractionError
from app.domain.slides import SlideConfig, SlideState
from app.services.imaging.pipeline import load_image, read_slide_manifest, resolve_slide_image
from app.services.slides import SlideService

router = APIRouter(prefix="/api/v1/videos", tags=["slides"])


def service(request: Request) -> SlideService:
    result: SlideService = request.app.state.slide_service
    return result


Service = Annotated[SlideService, Depends(service)]


class ProcessingRequest(BaseModel):
    configuration: SlideConfig | None = None
    reprocess: bool = False


class BulkRequest(ProcessingRequest):
    video_ids: list[int] = Field(min_length=1, max_length=100)


@router.get("/slides/config")
def configuration(request: Request) -> SlideConfig:
    return request.app.state.settings.slide_processing  # type: ignore[no-any-return]


@router.post("/slides/bulk", status_code=202)
def bulk(payload: BulkRequest, jobs: Service) -> dict[str, object]:
    started: list[int] = []
    errors: list[dict[str, object]] = []
    for video_id in dict.fromkeys(payload.video_ids):
        try:
            jobs.start(video_id, payload.configuration, reprocess=payload.reprocess)
            started.append(video_id)
        except (ExtractionError, VideoNotFoundError, VideoExcludedError) as exc:
            errors.append({"video_id": video_id, "reason": str(exc)})
    return {"started_ids": started, "errors": errors}


@router.get("/{video_id}/slide-processing")
def progress(video_id: int, jobs: Service) -> SlideState:
    return jobs.state(video_id)


@router.post("/{video_id}/slide-processing", status_code=202)
def start(video_id: int, payload: ProcessingRequest, jobs: Service) -> SlideState:
    return jobs.start(video_id, payload.configuration, reprocess=payload.reprocess)


@router.post("/{video_id}/slide-processing/cancel")
def cancel(video_id: int, jobs: Service) -> SlideState:
    return jobs.cancel(video_id)


@router.post("/{video_id}/slide-processing/retry", status_code=202)
def retry(video_id: int, jobs: Service) -> SlideState:
    return jobs.start(video_id, retry=True)


@router.delete("/{video_id}/slide-processing")
def delete(video_id: int, jobs: Service) -> SlideState:
    return jobs.delete(video_id)


@router.get("/{video_id}/slides")
def listing(
    video_id: int, jobs: Service, page: int = Query(1, ge=1), page_size: int = Query(6, ge=1, le=24)
) -> dict[str, object]:
    directory = jobs.directory(video_id)
    manifest = read_slide_manifest(directory, validate_images=False)
    offset = (page - 1) * page_size
    return {
        "items": manifest.slides[offset : offset + page_size],
        "total": len(manifest.slides),
        "page": page,
        "page_size": page_size,
        "generation": directory.name,
        "warnings": manifest.warnings,
    }


@router.get("/{video_id}/slides/{generation}/{filename}")
def preview(video_id: int, generation: str, filename: str, jobs: Service) -> FileResponse:
    directory = jobs.directory(video_id)
    if generation != directory.name:
        raise HTTPException(409, "Generation changed; refresh slide listing.")
    manifest = read_slide_manifest(directory, validate_images=False)
    allowed = {
        name
        for slide in manifest.slides
        for name in (
            slide.processed_image_path,
            slide.cropped_image_path,
            slide.original_image_path,
            slide.obstruction_mask_path,
        )
        if name is not None
    }
    if filename not in allowed:
        raise HTTPException(404, "Slide image not found.")
    target = resolve_slide_image(directory, Path(manifest.extraction_directory), filename)
    load_image(target, manifest.configuration)
    return FileResponse(
        target, media_type="image/png", headers={"Cache-Control": "private, no-cache"}
    )
