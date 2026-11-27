"""HTTP boundary for PDF generation, preview, download, bulk ZIP, and PDF Library."""

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.domain.downloads import VideoNotFoundError
from app.domain.exclusion import VideoExcludedError
from app.domain.pdfs import PdfConfig, PdfError, PdfLibraryItem, PdfLibraryPage, PdfState
from app.domain.slides import SlideConflict, SlideError
from app.repositories.settings import SettingsRepository
from app.services.pdfs import PdfService

router = APIRouter(prefix="/api/v1", tags=["pdfs"])


def service(request: Request) -> PdfService:
    result: PdfService = request.app.state.pdf_service
    return result


Service = Annotated[PdfService, Depends(service)]


class PdfGenerateRequest(BaseModel):
    configuration: PdfConfig | None = None
    regenerate: bool = False


class PdfBulkGenerateRequest(PdfGenerateRequest):
    video_ids: list[int] = Field(min_length=1, max_length=100)


class PdfBulkZipRequest(BaseModel):
    video_ids: list[int] = Field(min_length=1, max_length=1000)


def _content_disposition(disposition: Literal["inline", "attachment"], filename: str) -> str:
    ascii_fallback = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in {'"', "\\"} else "_" for ch in filename
    )
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


def _cleanup_temp_file(path: Path) -> None:
    path.unlink(missing_ok=True)


@router.get("/pdfs/config")
def get_pdf_config(request: Request) -> PdfConfig:
    default_cfg: PdfConfig = request.app.state.settings.pdf_generation
    repo = SettingsRepository(request.app.state.sessions)
    cfg, _ = repo.get_pdf_settings(default_cfg)
    return cfg


@router.get("/pdfs", response_model=PdfLibraryPage)
def list_pdfs(
    jobs: Service,
    search: str | None = None,
    channel_id: int | None = Query(default=None, ge=1),
    published_after: datetime | None = None,
    published_before: datetime | None = None,
    sort_by: Literal[
        "generated_at", "published_at", "title", "page_count", "file_size_bytes"
    ] = "generated_at",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PdfLibraryPage:
    return jobs.list_library(
        search=search,
        channel_id=channel_id,
        published_after=published_after,
        published_before=published_before,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.post("/pdfs/bulk", status_code=202)
def bulk_generate_pdfs(payload: PdfBulkGenerateRequest, jobs: Service) -> dict[str, object]:
    started: list[int] = []
    errors: list[dict[str, object]] = []
    for video_id in dict.fromkeys(payload.video_ids):
        try:
            jobs.start(video_id, payload.configuration, regenerate=payload.regenerate)
            started.append(video_id)
        except (
            PdfError,
            SlideConflict,
            SlideError,
            VideoNotFoundError,
            VideoExcludedError,
        ) as exc:
            errors.append({"video_id": video_id, "reason": str(exc)})
    return {"started_ids": started, "errors": errors}


@router.post("/pdfs/download-zip")
def download_pdfs_zip(
    payload: PdfBulkZipRequest,
    background_tasks: BackgroundTasks,
    jobs: Service,
) -> FileResponse:
    zip_path, unavailable = jobs.build_zip_archive(payload.video_ids)
    background_tasks.add_task(_cleanup_temp_file, zip_path)
    headers = {
        "Content-Disposition": _content_disposition("attachment", "lecture-slides.zip"),
        "Cache-Control": "private, no-cache",
        "X-Unavailable-Count": str(len(unavailable)),
    }
    return FileResponse(
        zip_path,
        media_type="application/zip",
        headers=headers,
    )


@router.get("/pdfs/{video_id}", response_model=PdfLibraryItem)
def get_pdf_metadata(video_id: int, jobs: Service) -> PdfLibraryItem:
    return jobs.get_library_item(video_id)


@router.get("/pdfs/{video_id}/preview")
def preview_pdf(video_id: int, jobs: Service) -> FileResponse:
    path, item = jobs.resolve_pdf_file(video_id)
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": _content_disposition("inline", item.pdf_filename),
            "Cache-Control": "private, no-cache",
        },
    )


@router.get("/pdfs/{video_id}/download")
def download_pdf(video_id: int, jobs: Service) -> FileResponse:
    path, item = jobs.resolve_pdf_file(video_id)
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": _content_disposition("attachment", item.pdf_filename),
            "Cache-Control": "private, no-cache",
        },
    )


@router.delete("/pdfs/{video_id}", response_model=PdfState)
def delete_pdf_from_library(video_id: int, jobs: Service) -> PdfState:
    return jobs.delete(video_id)


@router.get("/videos/{video_id}/pdf", response_model=PdfState)
def get_video_pdf_state(video_id: int, jobs: Service) -> PdfState:
    return jobs.state(video_id)


@router.post("/videos/{video_id}/pdf", status_code=202, response_model=PdfState)
def generate_video_pdf(
    video_id: int,
    jobs: Service,
    payload: PdfGenerateRequest | None = None,
) -> PdfState:
    req = payload or PdfGenerateRequest()
    return jobs.start(video_id, req.configuration, regenerate=req.regenerate)


@router.post("/videos/{video_id}/pdf/cancel", response_model=PdfState)
def cancel_video_pdf(video_id: int, jobs: Service) -> PdfState:
    return jobs.cancel(video_id)


@router.post("/videos/{video_id}/pdf/retry", status_code=202, response_model=PdfState)
def retry_video_pdf(video_id: int, jobs: Service) -> PdfState:
    return jobs.start(video_id, retry=True)


@router.delete("/videos/{video_id}/pdf", response_model=PdfState)
def delete_video_pdf(video_id: int, jobs: Service) -> PdfState:
    return jobs.delete(video_id)
