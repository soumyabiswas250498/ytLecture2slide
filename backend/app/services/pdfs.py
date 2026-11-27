"""Single-owner PDF generation jobs, recovery, cancellation, and safe file/ZIP lifecycle."""

import errno
import logging
import shutil
import threading
import time
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from app.core.config import Settings
from app.domain.downloads import VideoNotFoundError
from app.domain.exclusion import VideoExcludedError, format_exclusion_reason
from app.domain.pdfs import (
    PdfCancelled,
    PdfConfig,
    PdfConflict,
    PdfDocumentMetadata,
    PdfError,
    PdfImageInput,
    PdfLibraryItem,
    PdfLibraryPage,
    PdfNotFoundError,
    PdfState,
)
from app.domain.slides import SlideConflict, SlideError
from app.infrastructure.models import utc_now
from app.infrastructure.pdf_generator import PyMuPdfGenerator, build_pdf_filename
from app.repositories.channels import ChannelRepository
from app.repositories.pdfs import PdfRepository
from app.repositories.settings import SettingsRepository
from app.repositories.videos import VideoRepository
from app.services.extraction import _StopSignal
from app.services.imaging.pipeline import read_slide_manifest, resolve_slide_image
from app.services.slides import SlideService

logger = logging.getLogger(__name__)


class PdfService:
    """Application service managing persistent PDF generation jobs and PDF Library."""

    def __init__(
        self,
        *,
        videos: VideoRepository,
        channels: ChannelRepository,
        repository: PdfRepository,
        slides: SlideService,
        generator: PyMuPdfGenerator,
        settings: Settings,
        media_lock: threading.RLock,
        settings_repo: SettingsRepository | None = None,
    ) -> None:
        self.videos = videos
        self.channels = channels
        self.repository = repository
        self.slides = slides
        self.generator = generator
        self.settings = settings
        self.settings_repo = settings_repo
        self.lock = media_lock
        self.events: dict[int, threading.Event] = {}
        self.futures: dict[int, Future[None]] = {}
        self.stopping = threading.Event()
        assert settings.pdf_dir is not None
        self.root = settings.pdf_dir
        self.pool = ThreadPoolExecutor(
            max_workers=settings.pdf_concurrent_limit,
            thread_name_prefix="pdfs",
        )

    def state(self, video_id: int) -> PdfState:
        if self.videos.get_by_id(video_id) is None:
            raise VideoNotFoundError("Video not found.")
        return self.repository.get(video_id)

    def assert_inactive(self, video_id: int) -> None:
        state = self.repository.get(video_id)
        if video_id in self.events or state.requested or state.status == "generating":
            raise PdfConflict("PDF generation is queued or active for this video.")

    def start(
        self,
        video_id: int,
        config: PdfConfig | None = None,
        *,
        retry: bool = False,
        regenerate: bool = False,
    ) -> PdfState:
        with self.lock:
            if self.stopping.is_set():
                raise PdfConflict("PDF generator is shutting down.")
            state = self.state(video_id)
            video = self.videos.get_by_id(video_id)
            if video is not None and video.is_excluded:
                raise VideoExcludedError(
                    format_exclusion_reason(video.excluded_keywords),
                    video.excluded_keywords,
                )
            self.assert_inactive(video_id)
            self.slides.assert_inactive(video_id)

            try:
                slide_dir = self.slides.directory(video_id)
                manifest = read_slide_manifest(slide_dir, validate_images=False)
            except SlideConflict as exc:
                raise PdfConflict(str(exc)) from exc
            except SlideError as exc:
                raise PdfError(str(exc)) from exc

            if retry and state.status not in {"failed", "cancelled"}:
                raise PdfConflict("Only failed or cancelled PDF generation can be retried.")
            if (
                state.pdf_path
                and state.status == "generated"
                and Path(state.pdf_path).is_file()
                and not (retry or regenerate)
            ):
                raise PdfConflict("PDF already exists; explicitly request regeneration.")

            default_cfg = (
                self.settings_repo.get_pdf_settings(self.settings.pdf_generation)[0]
                if self.settings_repo is not None
                else self.settings.pdf_generation
            )
            base = (
                PdfConfig.model_validate_json(state.configuration)
                if retry and state.configuration and state.configuration != "{}"
                else default_cfg
            )
            if config is not None:
                overrides = base.model_dump()
                overrides.update(config.model_dump(exclude_unset=True))
                resolved_config = PdfConfig.model_validate(overrides)
            else:
                resolved_config = base

            self.root.mkdir(parents=True, exist_ok=True)
            if (
                resolved_config.min_free_disk_mb > 0
                and shutil.disk_usage(self.root).free
                < resolved_config.min_free_disk_mb * 1024 * 1024
            ):
                raise PdfError("Insufficient disk space for PDF generation.")

            claimed = self.repository.claim(
                video_id,
                resolved_config,
                total_pages=len(manifest.slides),
                source_slide_generation=slide_dir.name,
            )
            self._enqueue(claimed)
            return claimed

    def _enqueue(self, state: PdfState) -> None:
        event = threading.Event()
        self.events[state.video_id] = event
        future = self.pool.submit(self._run, state, event)
        self.futures[state.video_id] = future
        future.add_done_callback(lambda result: self._report(state.video_id, result))

    def get_future(self, video_id: int) -> Future[None] | None:
        with self.lock:
            return self.futures.get(video_id)

    def _report(self, video_id: int, future: Future[None]) -> None:
        if not future.cancelled() and (error := future.exception()) is not None:
            logger.error(
                "PDF worker failure",
                extra={"job_id": f"pdf:{video_id}"},
                exc_info=(type(error), error, error.__traceback__),
            )
            with self.lock:
                state = self.repository.get(video_id)
                if state.requested and not self.stopping.is_set():
                    self.repository.save(
                        video_id,
                        status="failed",
                        requested=False,
                        error="Unexpected PDF worker failure; check logs and retry.",
                    )

    def recover(self) -> None:
        for state in self.repository.recoverable():
            with self.lock:
                if state.video_id in self.events:
                    continue
                video = self.videos.get_by_id(state.video_id)
                if video is not None and video.is_excluded:
                    self.repository.save(
                        state.video_id,
                        status="cancelled",
                        requested=False,
                        error=format_exclusion_reason(video.excluded_keywords),
                    )
                    continue
                if state.retry_count >= self.settings.pdf_retry_attempts:
                    self.repository.save(
                        state.video_id,
                        status="failed",
                        requested=False,
                        error="PDF recovery retry limit exceeded.",
                    )
                    continue
                updated = self.repository.save(
                    state.video_id,
                    status="pending",
                    retry_count=state.retry_count + 1,
                )
                self._enqueue(updated)

    def cancel(self, video_id: int) -> PdfState:
        with self.lock:
            state = self.state(video_id)
            if not state.requested:
                raise PdfConflict("No active PDF generation.")
            if event := self.events.get(video_id):
                event.set()
            return self.repository.save(
                video_id,
                status="cancelled",
                requested=False,
                error="PDF generation cancelled by user.",
            )

    def delete(self, video_id: int) -> PdfState:
        with self.lock:
            state = self.state(video_id)
            self.assert_inactive(video_id)
            if state.pdf_path:
                target = self._validate_pdf_path(Path(state.pdf_path))
                if target.exists():
                    target.unlink()
            return self.repository.save(
                video_id,
                source_slide_generation=None,
                status="pending",
                requested=False,
                progress=0.0,
                completed_pages=0,
                total_pages=0,
                pdf_path=None,
                pdf_filename=None,
                page_count=0,
                file_size_bytes=0,
                started_at=None,
                completed_at=None,
                retry_count=0,
                error=None,
            )

    def list_library(
        self,
        *,
        search: str | None = None,
        channel_id: int | None = None,
        published_after: datetime | None = None,
        published_before: datetime | None = None,
        sort_by: Literal[
            "generated_at", "published_at", "title", "page_count", "file_size_bytes"
        ] = "generated_at",
        sort_order: Literal["asc", "desc"] = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> PdfLibraryPage:
        return self.repository.list_library(
            search=search,
            channel_id=channel_id,
            published_after=published_after,
            published_before=published_before,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
        )

    def get_library_item(self, video_id: int) -> PdfLibraryItem:
        item = self.repository.get_library_item(video_id)
        if item is None:
            raise PdfNotFoundError("Generated PDF not found.")
        return item

    def resolve_pdf_file(self, video_id: int) -> tuple[Path, PdfLibraryItem]:
        state = self.state(video_id)
        item = self.repository.get_library_item(video_id)
        if not state.pdf_path or item is None:
            raise PdfNotFoundError("Generated PDF not found.")
        target = self._validate_pdf_path(Path(state.pdf_path))
        if not target.is_file():
            raise PdfNotFoundError("Generated PDF file is missing from storage.")
        return target, item

    def build_zip_archive(self, video_ids: list[int]) -> tuple[Path, list[dict[str, object]]]:
        """Stream selected PDFs into a temporary ZIP file on disk."""
        unique_ids = list(dict.fromkeys(video_ids))
        if not unique_ids:
            raise PdfError("Select at least one PDF to download.")
        if len(unique_ids) > self.settings.pdf_zip_max_files:
            raise PdfError(
                f"Cannot bundle more than {self.settings.pdf_zip_max_files} PDFs in a single ZIP."
            )

        valid_entries: list[tuple[Path, str, int]] = []
        unavailable: list[dict[str, object]] = []
        used_names: set[str] = set()
        total_bytes = 0

        for vid in unique_ids:
            try:
                path, item = self.resolve_pdf_file(vid)
                size = path.stat().st_size
            except (VideoNotFoundError, PdfNotFoundError, PdfError) as exc:
                unavailable.append({"video_id": vid, "reason": str(exc)})
                continue

            archive_name = item.pdf_filename or path.name
            if archive_name in used_names:
                stem = Path(archive_name).stem
                suffix = Path(archive_name).suffix or ".pdf"
                candidate = f"{stem}_{vid}{suffix}"
                counter = 2
                while candidate in used_names:
                    candidate = f"{stem}_{vid}_{counter}{suffix}"
                    counter += 1
                archive_name = candidate
            used_names.add(archive_name)
            total_bytes += size
            valid_entries.append((path, archive_name, size))

        if not valid_entries:
            raise PdfNotFoundError("None of the selected PDFs are available for download.")
        if total_bytes > self.settings.pdf_zip_max_total_bytes:
            raise PdfError("Selected PDFs exceed the maximum ZIP archive size limit.")

        self.root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.root).free < total_bytes + (
            self.settings.pdf_min_free_disk_mb * 1024 * 1024
        ):
            raise PdfError("Insufficient disk space to build ZIP archive.")

        zip_path = self.root / f".bundle_{uuid4().hex}.tmp.zip"
        try:
            with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_STORED) as zf:
                for file_path, archive_name, _ in valid_entries:
                    zf.write(file_path, arcname=archive_name)
        except Exception:
            zip_path.unlink(missing_ok=True)
            raise

        return zip_path, unavailable

    def shutdown(self) -> None:
        self.stopping.set()
        self.pool.shutdown(wait=True, cancel_futures=True)

    def _validate_pdf_path(self, path: Path) -> Path:
        if self.root.is_symlink() or path.is_symlink():
            raise PdfError("Unsafe PDF path.")
        resolved_root = self.root.resolve()
        resolved_path = path.resolve()
        if not resolved_path.is_relative_to(resolved_root) or resolved_path == resolved_root:
            raise PdfError("PDF path escapes configured PDF directory.")
        return path

    def _target_output_path(
        self,
        *,
        video_id: int,
        filename: str,
        existing_pdf_path: str | None,
    ) -> tuple[Path, str]:
        """Choose a collision-free path inside PDF_DIR."""
        candidate = self.root / filename
        if existing_pdf_path and Path(existing_pdf_path).resolve() == candidate.resolve():
            return candidate, filename
        if candidate.exists():
            stem = candidate.stem
            suffix = candidate.suffix or ".pdf"
            disambiguated = f"{stem}_{video_id}{suffix}"
            candidate = self.root / disambiguated
            return candidate, disambiguated
        return candidate, filename

    def _run(self, state: PdfState, event: threading.Event) -> None:
        video_id = state.video_id
        signal = _StopSignal(event, self.stopping)
        started_at = utc_now()

        def on_progress(done: int, total: int) -> None:
            with self.lock:
                if not signal.is_set():
                    self.repository.save(
                        video_id,
                        completed_pages=done,
                        total_pages=total,
                        progress=min(99.9, done / max(1, total) * 100.0),
                    )

        try:
            config = (
                PdfConfig.model_validate_json(state.configuration)
                if state.configuration and state.configuration != "{}"
                else self.settings.pdf_generation
            )
            attempt = state.retry_count
            previous_pdf_path = state.pdf_path

            while True:
                try:
                    if signal.is_set():
                        raise PdfCancelled("PDF generation interrupted.")
                    with self.lock:
                        self.repository.save(
                            video_id,
                            status="generating",
                            started_at=started_at,
                            completed_pages=0,
                            progress=0.0,
                        )

                    video = self.videos.get_by_id(video_id)
                    if video is None:
                        raise VideoNotFoundError("Video not found.")
                    channel = (
                        self.channels.get_by_id(video.channel_id)
                        if video.channel_id is not None
                        else None
                    )
                    channel_name = (
                        channel.name
                        if channel is not None
                        else (video.channel_name or "Unknown Channel")
                    )

                    slide_dir = self.slides.directory(video_id)
                    manifest = read_slide_manifest(slide_dir, validate_images=False)
                    extraction_dir = Path(manifest.extraction_directory)

                    image_inputs: list[PdfImageInput] = []
                    for slide in manifest.slides:
                        img_path = resolve_slide_image(
                            slide_dir, extraction_dir, slide.processed_image_path
                        )
                        image_inputs.append(
                            PdfImageInput(
                                image_path=img_path,
                                timestamp_seconds=slide.source_timestamps[0],
                                end_timestamp_seconds=slide.source_timestamps[-1],
                                slide_id=slide.slide_id,
                            )
                        )

                    filename = build_pdf_filename(
                        published_at=video.published_at,
                        channel_name=channel_name,
                        title=video.title,
                        youtube_video_id=video.youtube_video_id,
                    )
                    output_path, final_filename = self._target_output_path(
                        video_id=video_id,
                        filename=filename,
                        existing_pdf_path=previous_pdf_path,
                    )
                    metadata = PdfDocumentMetadata(
                        title=video.title,
                        channel_name=channel_name,
                        source_url=video.video_url,
                        youtube_video_id=video.youtube_video_id,
                        published_at=video.published_at,
                    )
                    result = self.generator.generate(
                        image_inputs,
                        metadata,
                        output_path,
                        config=config,
                        on_progress=on_progress,
                        cancel=signal,
                    )
                    break
                except OSError as exc:
                    if (
                        exc.errno not in {errno.EAGAIN, errno.EBUSY, errno.EINTR}
                        or attempt >= self.settings.pdf_retry_attempts
                    ):
                        raise
                    attempt += 1
                    self.repository.save(video_id, retry_count=attempt)
                    deadline = time.monotonic() + min(2**attempt, 30)
                    while time.monotonic() < deadline:
                        if event.wait(0.1) or self.stopping.is_set():
                            raise PdfCancelled("PDF retry interrupted.") from exc

            with self.lock:
                if signal.is_set():
                    raise PdfCancelled("PDF publication interrupted.")
                completed_at = utc_now()
                self.repository.save(
                    video_id,
                    source_slide_generation=slide_dir.name,
                    status="generated",
                    requested=False,
                    progress=100.0,
                    completed_pages=result.page_count,
                    total_pages=result.page_count,
                    pdf_path=str(result.output_path),
                    pdf_filename=final_filename,
                    page_count=result.page_count,
                    file_size_bytes=result.file_size_bytes,
                    completed_at=completed_at,
                    error=None,
                )
                # Clean up superseded file only if filename changed and new file is published.
                if (
                    previous_pdf_path
                    and Path(previous_pdf_path).resolve() != result.output_path.resolve()
                ):
                    old_path = Path(previous_pdf_path)
                    if (
                        not old_path.is_symlink()
                        and old_path.resolve().is_relative_to(self.root.resolve())
                        and old_path.is_file()
                    ):
                        old_path.unlink(missing_ok=True)
            logger.info("PDF generated and published", extra={"job_id": f"pdf:{video_id}"})
        except PdfCancelled:
            with self.lock:
                if not event.is_set():
                    self.repository.save(
                        video_id,
                        status="pending",
                        requested=True,
                        error="Interrupted by shutdown; awaiting recovery.",
                    )
        except (PdfError, SlideError, VideoNotFoundError, OSError, ValueError) as exc:
            logger.exception("PDF generation failed", extra={"job_id": f"pdf:{video_id}"})
            with self.lock:
                if not event.is_set():
                    self.repository.save(
                        video_id,
                        status="failed",
                        requested=False,
                        error=str(exc)
                        or "PDF generation failed. Check slide images, disk space, and logs.",
                    )
        finally:
            with self.lock:
                self.events.pop(video_id, None)
