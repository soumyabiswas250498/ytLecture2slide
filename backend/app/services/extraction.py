"""Persistent background extraction jobs in the existing single-owner monolith."""

from __future__ import annotations

import errno
import logging
import math
import shutil
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.domain.downloads import (
    DownloadError,
    DownloadStatus,
    InsufficientDiskSpaceError,
    VideoNotFoundError,
)
from app.domain.exclusion import VideoExcludedError, format_exclusion_reason
from app.domain.extraction import (
    ExtractionCancelled,
    ExtractionConflict,
    ExtractionError,
    ExtractionResult,
    FrameExtractor,
    ProgressCallback,
)
from app.infrastructure.frame_extractor import read_manifest
from app.repositories.extractions import ExtractionRepository, ExtractionState
from app.repositories.videos import VideoRepository
from app.services.storage_cleanup import StorageCleanupService

logger = logging.getLogger("app.services.extraction")


class _StopSignal:
    def __init__(self, cancel: threading.Event, shutdown: threading.Event) -> None:
        self.cancel = cancel
        self.shutdown = shutdown

    def is_set(self) -> bool:
        return self.cancel.is_set() or self.shutdown.is_set()


class ExtractionService:
    def __init__(
        self,
        *,
        videos: VideoRepository,
        repository: ExtractionRepository,
        extractor: FrameExtractor,
        settings: Settings,
        media_lock: threading.RLock,
    ) -> None:
        self.processing_guard: Callable[[int], None] | None = None
        self.delete_guard: Callable[[int], None] | None = None
        self._videos = videos
        self._repo = repository
        self._extractor = extractor
        self._settings = settings
        self._lock = media_lock
        self._events: dict[int, threading.Event] = {}
        self._futures: dict[int, Future[None]] = {}
        self._shutdown = threading.Event()
        self._pool = ThreadPoolExecutor(
            max_workers=settings.extraction_concurrent_limit, thread_name_prefix="frame-extraction"
        )

        assert settings.frame_dir is not None
        self.cleanup_service = StorageCleanupService(
            settings.frame_dir,
            state=repository.cleanup_state,
            active=lambda video_id: video_id in self._events,
            media_lock=media_lock,
            retention_hours=settings.cleanup_retention_hours,
        )

    def state(self, video_id: int) -> ExtractionState:
        if self._videos.get_by_id(video_id) is None:
            raise VideoNotFoundError("Video not found.")
        return self._repo.get(video_id)

    def assert_inactive(self, video_id: int) -> None:
        state = self._repo.get(video_id)
        if video_id in self._events or state.requested or state.status == "extracting":
            raise ExtractionConflict("Frame extraction is queued or running for this video.")

    def _source(self, video_id: int) -> Path:
        video = self._videos.get_by_id(video_id)
        if video is None:
            raise VideoNotFoundError("Video not found.")
        if video.download_status != DownloadStatus.DOWNLOADED or not video.local_video_path:
            raise ExtractionConflict("A verified downloaded source video is required.")
        source = Path(video.local_video_path)
        assert self._settings.download_dir is not None
        if source.is_symlink() or not source.resolve().is_relative_to(self._settings.download_dir):
            raise ExtractionError("Source is outside the configured download directory.")
        if not source.is_file() or source.stat().st_size == 0:
            raise ExtractionError("Downloaded source video is unavailable.")
        return source

    def start(
        self, video_id: int, interval: float | None = None, *, retry: bool = False
    ) -> ExtractionState:
        with self._lock:
            if self._shutdown.is_set():
                raise ExtractionConflict("Extractor is shutting down.")
            video = self._videos.get_by_id(video_id)
            if video is not None and video.is_excluded:
                raise VideoExcludedError(
                    format_exclusion_reason(video.excluded_keywords),
                    video.excluded_keywords,
                )
            if self.processing_guard:
                self.processing_guard(video_id)
            self._source(video_id)
            assert self._settings.frame_dir is not None
            if (
                shutil.disk_usage(self._settings.frame_dir).free
                < self._settings.extraction_min_free_disk_mb * 1024 * 1024
            ):
                raise InsufficientDiskSpaceError("Insufficient disk space for extraction.")
            self._video_directory(video_id)
            self.assert_inactive(video_id)
            state = self._repo.get(video_id)
            if retry and state.status not in {"failed", "cancelled"}:
                raise ExtractionConflict("Only failed or cancelled extraction can be retried.")
            if state.status == "extracted":
                raise ExtractionConflict(
                    "Frames already extracted; delete frames before extracting again."
                )
            interval = (
                interval
                if interval is not None
                else (
                    state.interval_seconds if retry else self._settings.extraction_interval_seconds
                )
            )
            if not math.isfinite(interval) or interval < 0.001:
                raise ExtractionError("Interval must be at least one millisecond.")
            state = self._repo.claim(video_id, interval)
            self._enqueue(state)
            return state

    def _enqueue(self, state: ExtractionState) -> None:
        event = threading.Event()
        self._events[state.video_id] = event
        future = self._pool.submit(self._run, state, event)
        self._futures[state.video_id] = future
        future.add_done_callback(
            lambda completed: self._report_worker_error(state.video_id, completed)
        )

    def get_future(self, video_id: int) -> Future[None] | None:
        with self._lock:
            return self._futures.get(video_id)

    @staticmethod
    def _report_worker_error(video_id: int, future: Future[None]) -> None:
        if future.cancelled():
            return
        error = future.exception()
        if error is not None:
            logger.error(
                "Unexpected extraction worker failure for video_id=%d",
                video_id,
                exc_info=(type(error), error, error.__traceback__),
                extra={"job_id": f"extraction:{video_id}"},
            )

    def recover(self) -> None:
        for state in self._repo.recoverable():
            with self._lock:
                if state.video_id in self._events:
                    continue
                video = self._videos.get_by_id(state.video_id)
                if video is not None and video.is_excluded:
                    self._repo.save(
                        state.video_id,
                        status="cancelled",
                        requested=False,
                        error=format_exclusion_reason(video.excluded_keywords),
                    )
                    continue
                if state.retry_count >= self._settings.extraction_retry_attempts:
                    self._repo.save(
                        state.video_id,
                        status="failed",
                        requested=False,
                        error="Extraction recovery retry limit exceeded.",
                    )
                    continue
                state = self._repo.save(
                    state.video_id, status="pending", retry_count=state.retry_count + 1
                )
                self._enqueue(state)

    def cancel(self, video_id: int) -> ExtractionState:
        with self._lock:
            state = self.state(video_id)
            if not state.requested:
                raise ExtractionConflict("No extraction is queued or running.")
            self._repo.save(
                video_id, status="cancelled", requested=False, error="Extraction cancelled by user."
            )
            event = self._events.get(video_id)
            if event:
                event.set()
            return self._repo.get(video_id)

    def _video_directory(self, video_id: int) -> Path:
        assert self._settings.frame_dir is not None
        directory = self._settings.frame_dir / str(video_id)
        if directory.is_symlink() or directory.resolve().parent != self._settings.frame_dir:
            raise ExtractionError("Unsafe frame directory.")
        return directory

    def directory(self, video_id: int) -> Path:
        state = self.state(video_id)
        if not state.frame_directory:
            raise ExtractionConflict("No successful frame output is available.")
        assert self._settings.frame_dir is not None
        directory = Path(state.frame_directory)
        if directory.is_symlink() or not directory.resolve().is_relative_to(
            self._settings.frame_dir / str(video_id)
        ):
            raise ExtractionError("Unsafe frame directory.")
        return directory

    def delete(self, video_id: int) -> ExtractionState:
        with self._lock:
            self.state(video_id)
            if self.delete_guard:
                self.delete_guard(video_id)
            elif self.processing_guard:
                self.processing_guard(video_id)
            self.assert_inactive(video_id)
            assert self._settings.frame_dir is not None
            directory = self._settings.frame_dir / str(video_id)
            if directory.is_symlink() or directory.resolve().parent != self._settings.frame_dir:
                raise ExtractionError("Unsafe frame directory.")
            if directory.exists():
                shutil.rmtree(directory)
            return self._repo.save(
                video_id,
                status="pending",
                requested=False,
                progress=0,
                frame_count=0,
                expected_count=None,
                frame_directory=None,
                manifest_path=None,
                started_at=None,
                completed_at=None,
                retry_count=0,
                error=None,
            )

    def shutdown(self) -> None:
        with self._lock:
            self._shutdown.set()
        self._pool.shutdown(wait=True, cancel_futures=True)

    def _reusable_result(
        self, source: Path, video_id: int, interval: float
    ) -> tuple[Path, ExtractionResult] | None:
        assert self._settings.frame_dir is not None
        stat = source.stat()
        for manifest in (self._settings.frame_dir / str(video_id)).glob("*/manifest.json"):
            directory = manifest.parent
            if directory.is_symlink() or manifest.is_symlink():
                continue
            try:
                result = read_manifest(directory)
            except (ExtractionError, OSError, ValueError):
                logger.warning("Preserved invalid extraction output for video_id=%d", video_id)
                continue
            if (
                result.video_id == str(video_id)
                and result.source_path == str(source.resolve())
                and result.source_size_bytes == stat.st_size
                and result.source_mtime_ns == stat.st_mtime_ns
                and result.interval_seconds == interval
                and result.start_timestamp == 0
            ):
                return directory, result
        return None

    def _extract_with_retry(
        self,
        source: Path,
        output: Path,
        state: ExtractionState,
        event: threading.Event,
        progress: ProgressCallback,
    ) -> tuple[Path, ExtractionResult]:
        attempt = state.retry_count
        while True:
            try:
                result = self._extractor.extract(
                    source,
                    output,
                    video_id=str(state.video_id),
                    interval=state.interval_seconds,
                    on_progress=progress,
                    cancel=_StopSignal(event, self._shutdown),
                )
                return output, result
            except OSError as exc:
                if (
                    exc.errno not in {errno.EAGAIN, errno.EBUSY, errno.EINTR}
                    or attempt >= self._settings.extraction_retry_attempts
                ):
                    raise
                attempt += 1
                self._repo.save(
                    state.video_id,
                    retry_count=attempt,
                    error="Transient resource error; retrying extraction.",
                )
                deadline = time.monotonic() + min(2**attempt, 30)
                while time.monotonic() < deadline:
                    if event.wait(0.1) or self._shutdown.is_set():
                        raise ExtractionCancelled("Extraction interrupted during retry.") from exc
                output = output.parent / uuid4().hex

    def _run(self, state: ExtractionState, event: threading.Event) -> None:
        video_id = state.video_id
        last_write = 0.0

        def progress(count: int, expected: int) -> None:
            nonlocal last_write
            now = time.monotonic()
            if now - last_write >= self._settings.extraction_progress_interval_seconds:
                with self._lock:
                    if event.is_set() or self._shutdown.is_set():
                        return
                    self._repo.save(
                        video_id,
                        frame_count=count,
                        expected_count=expected,
                        progress=min(99.9, count / expected * 100),
                    )
                last_write = now

        try:
            if event.is_set() or self._shutdown.is_set():
                raise ExtractionCancelled("Extraction interrupted.")
            source = self._source(video_id)
            assert self._settings.frame_dir is not None
            output = self._video_directory(video_id) / uuid4().hex
            with self._lock:
                if event.is_set() or self._shutdown.is_set():
                    raise ExtractionCancelled("Extraction interrupted before decoding.")
                self._repo.save(video_id, status="extracting", started_at=datetime.now(UTC))
            reusable = self._reusable_result(source, video_id, state.interval_seconds)
            if reusable is not None:
                output, extracted = reusable
            else:
                output, extracted = self._extract_with_retry(source, output, state, event, progress)
            result = extracted
            with self._lock:
                if event.is_set() or self._shutdown.is_set():
                    raise ExtractionCancelled("Extraction interrupted before publication.")
                self._repo.save(
                    video_id,
                    status="extracted",
                    requested=False,
                    progress=100,
                    frame_count=result.frame_count,
                    expected_count=result.frame_count,
                    frame_directory=str(output),
                    manifest_path=str(output / "manifest.json"),
                    completed_at=datetime.now(UTC),
                    error=None,
                )
            logger.info(
                "Frames extracted for video_id=%d, count=%d",
                video_id,
                result.frame_count,
                extra={"job_id": f"extraction:{video_id}"},
            )
        except ExtractionCancelled:
            with self._lock:
                if not event.is_set():
                    self._repo.save(
                        video_id,
                        status="pending",
                        requested=True,
                        error="Extraction interrupted by shutdown; awaiting recovery.",
                    )
        except (DownloadError, ExtractionError, OSError, ValueError) as exc:
            logger.warning(
                "Extraction failed for video_id=%d",
                video_id,
                exc_info=True,
                extra={"job_id": f"extraction:{video_id}"},
            )
            message = (
                "Insufficient storage space or quota for extraction. Free space and retry."
                if isinstance(exc, OSError) and exc.errno in {errno.ENOSPC, errno.EDQUOT}
                else str(exc)
                if isinstance(exc, (DownloadError, ExtractionError))
                else (
                    "Local extraction failed. Check FFmpeg installation, "
                    "storage permissions and disk space."
                )
            )
            with self._lock:
                if not event.is_set():
                    self._repo.save(video_id, status="failed", requested=False, error=message)
        finally:
            with self._lock:
                self._events.pop(video_id, None)
            self.cleanup_service.cleanup(dry_run=self._settings.cleanup_dry_run)
