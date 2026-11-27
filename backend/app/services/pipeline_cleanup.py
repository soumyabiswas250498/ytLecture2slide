"""Safe, idempotent intermediate cleanup after validated PDF publication."""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

import pymupdf

from app.core.config import Settings
from app.domain.downloads import DownloadStatus, VideoNotFoundError
from app.domain.extraction import ExtractionStatus
from app.domain.pdfs import PdfError, PdfState
from app.domain.pipeline import IntermediateCleanupResult
from app.infrastructure.models import utc_now
from app.infrastructure.ytdlp_downloader import sanitize_youtube_video_id
from app.repositories.extractions import ExtractionRepository
from app.repositories.pdfs import PdfRepository
from app.repositories.slides import SlideRepository
from app.repositories.videos import VideoRepository
from app.services.downloader import VideoDownloadService
from app.services.extraction import ExtractionService
from app.services.pdfs import PdfService
from app.services.slides import SlideService

logger = logging.getLogger("app.services.pipeline_cleanup")


def _safe_unlink_file(path: Path, *, allowed_root: Path) -> tuple[bool, int]:
    """Unlink a regular file only if it is strictly inside allowed_root and not a symlink."""
    if path.is_symlink():
        raise PdfError(f"Refusing to delete symlink: {path}")
    resolved_root = allowed_root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise PdfError(f"Refusing to delete file outside managed storage: {path}")
    if not resolved_path.is_file():
        return False, 0
    size = resolved_path.stat().st_size
    resolved_path.unlink()
    return True, size


def _safe_rmtree_contents(directory: Path, *, allowed_root: Path) -> tuple[int, int]:
    """Remove a managed video directory and count deleted files and bytes."""
    if not directory.exists() and not directory.is_symlink():
        return 0, 0
    if directory.is_symlink():
        raise PdfError(f"Refusing to delete symlink directory: {directory}")
    resolved_root = allowed_root.resolve()
    resolved_dir = directory.resolve()
    if resolved_dir == resolved_root or not resolved_dir.is_relative_to(resolved_root):
        raise PdfError(f"Refusing to delete directory outside managed storage: {directory}")
    if not resolved_dir.is_dir():
        return 0, 0

    deleted_files = 0
    freed_bytes = 0
    for item in resolved_dir.rglob("*"):
        if item.is_symlink():
            raise PdfError(f"Refusing to delete symlink inside intermediate directory: {item}")
        if item.is_file():
            freed_bytes += item.stat().st_size
            deleted_files += 1
    shutil.rmtree(resolved_dir)
    return deleted_files, freed_bytes


class PipelineCleanupService:
    """Validates published PDFs and safely removes job-owned intermediate artifacts."""

    def __init__(
        self,
        *,
        settings: Settings,
        media_lock: threading.RLock,
        video_repo: VideoRepository,
        extraction_repo: ExtractionRepository,
        slide_repo: SlideRepository,
        pdf_repo: PdfRepository,
        download_service: VideoDownloadService,
        extraction_service: ExtractionService,
        slide_service: SlideService,
        pdf_service: PdfService,
    ) -> None:
        self._settings = settings
        self._lock = media_lock
        self._videos = video_repo
        self._extractions = extraction_repo
        self._slides = slide_repo
        self._pdfs = pdf_repo
        self._download_service = download_service
        self._extraction_service = extraction_service
        self._slide_service = slide_service
        self._pdf_service = pdf_service

    def validate_video_pdf(
        self,
        video_id: int,
        *,
        expected_slide_generation: str | None = None,
    ) -> PdfState:
        """Verify PDF existence, readability, page count, and slide-generation match."""
        pdf_state = self._pdfs.get(video_id)
        if pdf_state.status != "generated" or not pdf_state.pdf_path:
            raise PdfError("PDF has not been generated for this video.")
        if (
            expected_slide_generation is not None
            and pdf_state.source_slide_generation != expected_slide_generation
        ):
            raise PdfError(
                "Published PDF belongs to a different slide generation than the current slides."
            )
        pdf_path = Path(pdf_state.pdf_path)
        assert self._settings.pdf_dir is not None
        allowed_pdf_root = self._settings.pdf_dir.resolve()
        if pdf_path.is_symlink() or not pdf_path.resolve().is_relative_to(allowed_pdf_root):
            raise PdfError("Published PDF path is outside managed PDF storage.")
        if not pdf_path.is_file() or pdf_path.stat().st_size <= 0:
            raise PdfError("Published PDF file is missing or empty.")

        try:
            with pymupdf.open(str(pdf_path)) as doc:
                page_count = len(doc)
                if page_count <= 0:
                    raise PdfError("Published PDF has zero pages.")
                if pdf_state.page_count > 0 and page_count != pdf_state.page_count:
                    raise PdfError(
                        f"Published PDF page count mismatch: expected {pdf_state.page_count}, "
                        f"got {page_count}."
                    )
                for idx in range(page_count):
                    images = doc[idx].get_images(full=True)
                    if len(images) != 1:
                        raise PdfError(
                            f"Published PDF page {idx + 1} expected 1 embedded image, "
                            f"found {len(images)}."
                        )
        except PdfError:
            raise
        except Exception as exc:
            raise PdfError(f"Published PDF failed integrity validation: {exc}") from exc

        return pdf_state

    def cleanup_video_intermediates(
        self,
        video_id: int,
        *,
        expected_slide_generation: str | None = None,
    ) -> IntermediateCleanupResult:
        """Validate the video's PDF and safely delete downloaded video, frames, and slides."""
        with self._lock:
            video = self._videos.get_by_id(video_id)
            if video is None:
                raise VideoNotFoundError(f"Video {video_id} not found.")

            # Never clean while any stage is queued or active for this video.
            if self._download_service.is_download_active(video_id):
                raise PdfError("Cannot clean intermediates while download is active.")
            self._extraction_service.assert_inactive(video_id)
            self._slide_service.assert_inactive(video_id)
            self._pdf_service.assert_inactive(video_id)

            # Critical safety gate: validate PDF before deleting anything.
            self.validate_video_pdf(video_id, expected_slide_generation=expected_slide_generation)

            deleted_files = 0
            freed_bytes = 0

            # 1. Remove downloaded source video (only if inside managed download_dir).
            assert self._settings.download_dir is not None
            download_root = self._settings.download_dir.resolve()
            if video.local_video_path:
                local_path = Path(video.local_video_path)
                if not local_path.is_symlink() and local_path.resolve().is_relative_to(
                    download_root
                ):
                    removed, size = _safe_unlink_file(local_path, allowed_root=download_root)
                    if removed:
                        deleted_files += 1
                        freed_bytes += size
                else:
                    logger.info(
                        "Preserving user-owned source video outside managed download_dir: %s",
                        local_path,
                    )

            # Remove any leftover .part or temporary files for this YouTube video ID.
            if video.youtube_video_id and download_root.is_dir():
                try:
                    safe_id = sanitize_youtube_video_id(video.youtube_video_id)
                    for candidate in download_root.glob(f"{safe_id}*"):
                        if candidate.is_file() and not candidate.is_symlink():
                            removed, size = _safe_unlink_file(candidate, allowed_root=download_root)
                            if removed:
                                deleted_files += 1
                                freed_bytes += size
                except Exception:
                    logger.warning(
                        "Failed scanning partial download files for video_id=%d",
                        video_id,
                        exc_info=True,
                    )

            # 2. Remove extracted frames (primary + additional + manifests).
            assert self._settings.frame_dir is not None
            frame_video_dir = self._settings.frame_dir / str(video_id)
            f_count, f_bytes = _safe_rmtree_contents(
                frame_video_dir, allowed_root=self._settings.frame_dir
            )
            deleted_files += f_count
            freed_bytes += f_bytes

            # 3. Remove processed slide images and manifests.
            assert self._settings.temp_dir is not None
            slides_root = self._settings.temp_dir / "slides"
            slide_video_dir = slides_root / str(video_id)
            s_count, s_bytes = _safe_rmtree_contents(slide_video_dir, allowed_root=slides_root)
            deleted_files += s_count
            freed_bytes += s_bytes

            # 4. Persist explicit Cleaned state while preserving statistics & PDF record.
            cleaned_at = utc_now()
            clear_path = bool(
                video.local_video_path
                and not Path(video.local_video_path).is_symlink()
                and Path(video.local_video_path).resolve().is_relative_to(download_root)
            )
            self._videos.mark_intermediates_cleaned(
                video_id,
                cleaned=True,
                cleaned_at=cleaned_at,
                clear_download_path=clear_path,
                download_status=DownloadStatus.CLEANED if clear_path else None,
            )
            ext_state = self._extractions.get(video_id)
            if ext_state.status != ExtractionStatus.PENDING or ext_state.frame_directory:
                self._extractions.save(
                    video_id,
                    status=ExtractionStatus.CLEANED.value,
                    requested=False,
                    frame_directory=None,
                    manifest_path=None,
                    error=None,
                )
            slide_state = self._slides.get(video_id)
            if slide_state.status != "pending" or slide_state.output_directory:
                self._slides.save(
                    video_id,
                    status="cleaned",
                    requested=False,
                    output_directory=None,
                    error=None,
                )

            logger.info(
                "Cleaned intermediates for video_id=%d deleted_files=%d freed_bytes=%d",
                video_id,
                deleted_files,
                freed_bytes,
                extra={"job_id": f"cleanup:{video_id}"},
            )
            return IntermediateCleanupResult(
                video_id=video_id,
                cleaned=True,
                deleted_files=deleted_files,
                freed_bytes=freed_bytes,
            )
