import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.domain.channels import (
    ChannelError,
    ChannelNotFoundError,
    ChannelValidationError,
    DuplicateChannelError,
    InvalidCsvError,
)
from app.domain.downloads import (
    DownloadAlreadyCompletedError,
    DownloadAlreadyInProgressError,
    DownloadError,
    InsufficientDiskSpaceError,
    InvalidDownloadStateError,
    VideoNotFoundError,
)
from app.domain.exclusion import VideoExcludedError
from app.domain.extraction import ExtractionConflict, ExtractionError
from app.domain.pdfs import PdfConflict, PdfError, PdfNotFoundError
from app.domain.videos import (
    DiscoveryAlreadyRunningError,
    QuotaExhaustedError,
    VideoDiscoveryError,
)

logger = logging.getLogger("app.errors")


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _format_validation_message(exc: RequestValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = [str(item) for item in err.get("loc", ()) if item not in {"body", "query", "path"}]
        msg = str(err.get("msg", "Invalid value"))
        # Strip Pydantic's "Value error, " prefix without ever echoing raw input values.
        msg = msg.removeprefix("Value error, ")
        parts.append(f"{'.'.join(loc)}: {msg}" if loc else msg)
    return "; ".join(parts) if parts else "Request parameters are invalid."


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ExtractionConflict)
    async def extraction_conflict(request: Request, exc: ExtractionConflict) -> JSONResponse:
        return error_response(409, "extraction_conflict", str(exc))

    @app.exception_handler(ExtractionError)
    async def extraction_error(request: Request, exc: ExtractionError) -> JSONResponse:
        return error_response(422, "extraction_error", str(exc))

    @app.exception_handler(PdfConflict)
    async def pdf_conflict(request: Request, exc: PdfConflict) -> JSONResponse:
        return error_response(409, "pdf_conflict", str(exc))

    @app.exception_handler(PdfNotFoundError)
    async def pdf_not_found(request: Request, exc: PdfNotFoundError) -> JSONResponse:
        return error_response(404, "pdf_not_found", str(exc))

    @app.exception_handler(PdfError)
    async def pdf_error(request: Request, exc: PdfError) -> JSONResponse:
        return error_response(422, "pdf_error", str(exc))

    @app.exception_handler(ChannelNotFoundError)
    async def channel_not_found(request: Request, exc: ChannelNotFoundError) -> JSONResponse:
        return error_response(404, "channel_not_found", str(exc))

    @app.exception_handler(DuplicateChannelError)
    async def duplicate_channel(request: Request, exc: DuplicateChannelError) -> JSONResponse:
        return error_response(409, "duplicate_channel", str(exc))

    @app.exception_handler(InvalidCsvError)
    async def invalid_csv(request: Request, exc: InvalidCsvError) -> JSONResponse:
        return error_response(422, "invalid_csv", str(exc))

    @app.exception_handler(ChannelValidationError)
    async def channel_validation(request: Request, exc: ChannelValidationError) -> JSONResponse:
        return error_response(422, "validation_error", str(exc))

    @app.exception_handler(ChannelError)
    async def channel_error(request: Request, exc: ChannelError) -> JSONResponse:
        return error_response(400, "channel_error", str(exc))

    @app.exception_handler(QuotaExhaustedError)
    async def quota_exhausted(request: Request, exc: QuotaExhaustedError) -> JSONResponse:
        return error_response(503, "quota_exhausted", str(exc))

    @app.exception_handler(DiscoveryAlreadyRunningError)
    async def discovery_already_running(
        request: Request, exc: DiscoveryAlreadyRunningError
    ) -> JSONResponse:
        return error_response(409, "discovery_already_running", str(exc))

    @app.exception_handler(VideoDiscoveryError)
    async def video_discovery_error(request: Request, exc: VideoDiscoveryError) -> JSONResponse:
        return error_response(422, "discovery_error", str(exc))

    @app.exception_handler(VideoNotFoundError)
    async def video_not_found(request: Request, exc: VideoNotFoundError) -> JSONResponse:
        return error_response(404, "video_not_found", str(exc))

    @app.exception_handler(VideoExcludedError)
    async def video_excluded(request: Request, exc: VideoExcludedError) -> JSONResponse:
        return error_response(409, "video_excluded", str(exc))

    @app.exception_handler(DownloadAlreadyInProgressError)
    async def download_already_in_progress(
        request: Request, exc: DownloadAlreadyInProgressError
    ) -> JSONResponse:
        return error_response(409, "download_in_progress", str(exc))

    @app.exception_handler(DownloadAlreadyCompletedError)
    async def download_already_completed(
        request: Request, exc: DownloadAlreadyCompletedError
    ) -> JSONResponse:
        return error_response(409, "download_already_completed", str(exc))

    @app.exception_handler(InvalidDownloadStateError)
    async def invalid_download_state(
        request: Request, exc: InvalidDownloadStateError
    ) -> JSONResponse:
        return error_response(409, "invalid_download_state", str(exc))

    @app.exception_handler(InsufficientDiskSpaceError)
    async def insufficient_disk_space(
        request: Request, exc: InsufficientDiskSpaceError
    ) -> JSONResponse:
        return error_response(507, "insufficient_disk_space", str(exc))

    @app.exception_handler(DownloadError)
    async def download_error(request: Request, exc: DownloadError) -> JSONResponse:
        return error_response(422, "download_error", str(exc))

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError) -> JSONResponse:
        return error_response(422, "configuration_error", str(exc))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        response = error_response(exc.status_code, "http_error", str(exc.detail))
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "validation_error", _format_validation_message(exc))

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled request error", exc_info=exc)
        return error_response(500, "internal_error", "An unexpected server error occurred.")
