"""Application service for video acquisition, progress tracking, recovery and cleanup."""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.domain.downloads import (
    BulkDownloadSummary,
    DownloadAlreadyCompletedError,
    DownloadAlreadyInProgressError,
    DownloadCancelledError,
    DownloadError,
    DownloadInterruptedError,
    DownloadProgress,
    DownloadRequest,
    DownloadStatus,
    InsufficientDiskSpaceError,
    InvalidDownloadStateError,
    MediaProbeValidator,
    VideoDownloaderAdapter,
    VideoNotFoundError,
)
from app.domain.videos import VideoEntity
from app.infrastructure.ytdlp_downloader import sanitize_youtube_video_id
from app.repositories.videos import VideoRepository

logger = logging.getLogger("app.services.downloader")

_DB_PROGRESS_MIN_INTERVAL_SECONDS = 2.0
_DB_PROGRESS_MIN_PERCENT_DELTA = 5.0
_DISK_CHECK_INTERVAL_SECONDS = 5.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


class VideoDownloadService:
    """Coordinates non-blocking video downloads, validation, recovery, cancellation and cleanup."""

    def __init__(
        self,
        *,
        video_repo: VideoRepository,
        downloader: VideoDownloaderAdapter,
        validator: MediaProbeValidator,
        settings: Settings,
        media_lock: threading.RLock | None = None,
        extraction_guard: Callable[[int], None] | None = None,
    ) -> None:
        self._repo = video_repo
        self._downloader = downloader
        self._validator = validator
        self._settings = settings
        self._lock = media_lock or threading.RLock()
        self._extraction_guard = extraction_guard
        self._active_videos: set[int] = set()
        self._cancel_events: dict[int, threading.Event] = {}
        self._live_progress: dict[int, DownloadProgress] = {}
        self._shutdown_event = threading.Event()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.download_concurrent_limit,
            thread_name_prefix="video-download",
        )
        self._shutting_down = False

    def recover_interrupted_downloads(self) -> int:
        """Automatically resume or re-enqueue interrupted/pending downloads on startup.

        Explicitly cancelled or completed downloads are never restarted.
        """
        recoverable = self._repo.list_recoverable_downloads()
        recovered_count = 0
        for video in recoverable:
            if self._shutting_down:
                break
            if video.download_retry_count >= self._settings.download_retry_attempts:
                self._repo.update_download_state(
                    video.id,
                    download_status=DownloadStatus.FAILED,
                    download_requested=False,
                    download_error="Download recovery exceeded maximum retry attempts.",
                )
                continue

            try:
                self._check_disk_space()
            except InsufficientDiskSpaceError as exc:
                self._repo.update_download_state(
                    video.id,
                    download_status=DownloadStatus.FAILED,
                    download_requested=False,
                    download_error=str(exc),
                )
                continue

            with self._lock:
                if video.id in self._active_videos:
                    continue
                cancel_event = threading.Event()
                self._active_videos.add(video.id)
                self._cancel_events[video.id] = cancel_event
                self._live_progress[video.id] = DownloadProgress(
                    video_id=video.id,
                    youtube_video_id=video.youtube_video_id,
                    status=DownloadStatus.DOWNLOADING,
                    progress_percent=video.download_progress,
                    downloaded_bytes=video.downloaded_bytes,
                    total_bytes=video.total_bytes,
                    is_live=False,
                )

            next_retry = video.download_retry_count + 1
            self._repo.update_download_state(
                video.id,
                download_status=DownloadStatus.DOWNLOADING,
                download_requested=True,
                download_retry_count=next_retry,
                clear_error=True,
            )
            self._executor.submit(self._run_download_task, video, cancel_event, next_retry)
            recovered_count += 1
            logger.info(
                "Recovered interrupted download for video_id=%d (attempt %d/%d)",
                video.id,
                next_retry,
                self._settings.download_retry_attempts,
            )

        return recovered_count

    def shutdown(self) -> None:
        """Signal shutdown, reject new requests, preserve .part files, and drain executor."""
        with self._lock:
            self._shutting_down = True
            self._shutdown_event.set()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def start_download(self, video_id: int) -> VideoEntity:
        with self._lock:
            if self._extraction_guard:
                self._extraction_guard(video_id)
            return self._start_download(video_id)

    def _start_download(self, video_id: int) -> VideoEntity:
        """Validate preconditions and enqueue a single video download."""
        with self._lock:
            if self._shutting_down:
                raise DownloadError("Downloader is shutting down.")

        video = self._repo.get_by_id(video_id)
        if video is None:
            raise VideoNotFoundError(f"Video {video_id} not found.")

        self._check_disk_space()

        with self._lock:
            if self._shutting_down:
                raise DownloadError("Downloader is shutting down.")
            if video_id in self._active_videos:
                raise DownloadAlreadyInProgressError(
                    f"Download is already in progress for video {video_id}."
                )
            if video.download_status == DownloadStatus.DOWNLOADED and self._has_valid_local_file(
                video
            ):
                raise DownloadAlreadyCompletedError(
                    f"Video {video_id} is already downloaded locally."
                )

            cancel_event = threading.Event()
            self._active_videos.add(video_id)
            self._cancel_events[video_id] = cancel_event
            self._live_progress[video_id] = DownloadProgress(
                video_id=video_id,
                youtube_video_id=video.youtube_video_id,
                status=DownloadStatus.DOWNLOADING,
                progress_percent=0.0,
                downloaded_bytes=0,
                total_bytes=None,
                is_live=True,
            )

        updated = self._repo.update_download_state(
            video_id,
            download_status=DownloadStatus.DOWNLOADING,
            download_progress=0.0,
            downloaded_bytes=0,
            download_requested=True,
            download_started_at=_utc_now(),
            download_retry_count=0,
            clear_file_metadata=False,
            clear_error=True,
        )
        assert updated is not None

        self._executor.submit(self._run_download_task, video, cancel_event, 0)
        return updated

    def start_bulk_download(self, video_ids: list[int]) -> BulkDownloadSummary:
        """Initiate downloads for multiple selected videos, reporting per-item outcomes."""
        summary = BulkDownloadSummary()
        seen: set[int] = set()
        for video_id in video_ids:
            if video_id in seen:
                continue
            seen.add(video_id)
            try:
                self.start_download(video_id)
                summary.started_ids.append(video_id)
            except (DownloadAlreadyInProgressError, DownloadAlreadyCompletedError) as exc:
                summary.skipped.append({"video_id": video_id, "reason": str(exc)})
            except DownloadError as exc:
                summary.errors.append({"video_id": video_id, "reason": str(exc)})
        return summary

    def get_progress(self, video_id: int) -> DownloadProgress:
        """Return live in-memory progress if active, otherwise construct from persisted state."""
        with self._lock:
            live = self._live_progress.get(video_id)
            if live is not None:
                return live

        video = self._repo.get_by_id(video_id)
        if video is None:
            raise VideoNotFoundError(f"Video {video_id} not found.")

        return DownloadProgress(
            video_id=video.id,
            youtube_video_id=video.youtube_video_id,
            status=video.download_status,
            progress_percent=video.download_progress,
            downloaded_bytes=video.downloaded_bytes,
            total_bytes=video.total_bytes,
            speed_bytes_per_sec=None,
            eta_seconds=None,
            is_live=False,
            error=video.download_error,
        )

    def get_active_progress(self) -> list[DownloadProgress]:
        """Return progress snapshots for all currently active downloads."""
        with self._lock:
            return list(self._live_progress.values())

    def cancel_download(self, video_id: int) -> VideoEntity:
        """Cancel an active download or clean up a stale downloading state."""
        with self._lock:
            video = self._repo.get_by_id(video_id)
            if video is None:
                raise VideoNotFoundError(f"Video {video_id} not found.")

            cancel_event = self._cancel_events.get(video_id)
            is_active = (
                video_id in self._active_videos
                and video.download_status != DownloadStatus.DOWNLOADED
            )

            if cancel_event is not None and is_active:
                cancel_event.set()
                logger.info("Cancellation requested for video_id=%d", video_id)
                updated = self._repo.update_download_state(
                    video_id,
                    download_status=DownloadStatus.CANCELLED,
                    download_requested=False,
                    download_error="Download cancelled by user.",
                )
                return updated or video

            if video.download_status == DownloadStatus.DOWNLOADING or video.download_requested:
                updated = self._repo.update_download_state(
                    video_id,
                    download_status=DownloadStatus.CANCELLED,
                    download_requested=False,
                    download_error="Download cancelled by user.",
                )
                return updated or video

            raise InvalidDownloadStateError(
                f"Video {video_id} is not currently downloading (status: {video.download_status})."
            )

    def retry_download(self, video_id: int) -> VideoEntity:
        """Retry a failed or cancelled download."""
        video = self._repo.get_by_id(video_id)
        if video is None:
            raise VideoNotFoundError(f"Video {video_id} not found.")

        retryable = {
            DownloadStatus.FAILED,
            DownloadStatus.CANCELLED,
            DownloadStatus.PENDING,
        }
        is_missing_downloaded_file = (
            video.download_status == DownloadStatus.DOWNLOADED
            and not self._has_valid_local_file(video)
        )
        if video.download_status not in retryable and not is_missing_downloaded_file:
            raise InvalidDownloadStateError(
                f"Cannot retry download in '{video.download_status}' state."
            )

        return self.start_download(video_id)

    def delete_local_video(self, video_id: int) -> VideoEntity:
        with self._lock:
            if self._extraction_guard:
                self._extraction_guard(video_id)
            return self._delete_local_video(video_id)

    def _delete_local_video(self, video_id: int) -> VideoEntity:
        """Safely delete the local video file and reset download metadata."""
        video = self._repo.get_by_id(video_id)
        if video is None:
            raise VideoNotFoundError(f"Video {video_id} not found.")

        with self._lock:
            if video_id in self._active_videos:
                raise DownloadAlreadyInProgressError(
                    f"Cannot delete video {video_id} while download is in progress."
                )

        if video.download_status == DownloadStatus.DOWNLOADING:
            raise DownloadAlreadyInProgressError(
                f"Cannot delete video {video_id} while download is in progress."
            )

        dest_root = self._download_dir().resolve()
        if video.local_video_path:
            target = Path(video.local_video_path).resolve()
            if not target.is_relative_to(dest_root):
                raise DownloadError(
                    "Refusing to delete file outside configured download directory."
                )
            if target.exists() and target.is_file():
                target.unlink()
                logger.info("Deleted local video file for video_id=%d: %s", video_id, target)

        self._cleanup_partial_files(video.youtube_video_id)

        updated = self._repo.update_download_state(
            video_id,
            download_status=DownloadStatus.PENDING,
            download_progress=0.0,
            downloaded_bytes=0,
            download_requested=False,
            download_retry_count=0,
            clear_file_metadata=True,
            clear_error=True,
        )
        assert updated is not None
        return updated

    # ------------------------------------------------------------------
    # Internal worker execution
    # ------------------------------------------------------------------

    def _run_download_task(
        self,
        video: VideoEntity,
        cancel_event: threading.Event,
        initial_attempt: int = 0,
    ) -> None:
        video_id = video.id
        dest_dir = self._download_dir()
        max_retries = self._settings.download_retry_attempts
        last_persisted_pct = video.download_progress
        last_db_write_at = time.monotonic()
        last_disk_check_at = time.monotonic()

        def _on_progress(progress: DownloadProgress) -> None:
            nonlocal last_persisted_pct, last_db_write_at, last_disk_check_at
            with self._lock:
                self._live_progress[video_id] = progress

            now = time.monotonic()
            if now - last_disk_check_at >= _DISK_CHECK_INTERVAL_SECONDS:
                last_disk_check_at = now
                remaining = (
                    max(0, progress.total_bytes - progress.downloaded_bytes)
                    if progress.total_bytes
                    else 0
                )
                self._check_disk_space(required_extra_bytes=remaining)

            pct_delta = abs(progress.progress_percent - last_persisted_pct)
            time_elapsed = now - last_db_write_at
            if (
                pct_delta >= _DB_PROGRESS_MIN_PERCENT_DELTA
                or time_elapsed >= _DB_PROGRESS_MIN_INTERVAL_SECONDS
            ):
                last_persisted_pct = progress.progress_percent
                last_db_write_at = now
                self._repo.update_download_state(
                    video_id,
                    download_status=DownloadStatus.DOWNLOADING,
                    download_progress=progress.progress_percent,
                    downloaded_bytes=progress.downloaded_bytes,
                    total_bytes=progress.total_bytes,
                )

        try:
            attempt = initial_attempt
            while True:
                if self._shutdown_event.is_set():
                    raise DownloadInterruptedError("Download interrupted by server shutdown.")
                if cancel_event.is_set():
                    raise DownloadCancelledError("Download cancelled by user.")

                try:
                    self._check_disk_space()
                    request = DownloadRequest(
                        video_id=video_id,
                        youtube_video_id=video.youtube_video_id,
                        video_url=video.video_url,
                        destination_dir=dest_dir,
                        max_resolution=self._settings.download_max_resolution,
                        audio_enabled=self._settings.download_audio_enabled,
                        connect_timeout_seconds=self._settings.download_connect_timeout_seconds,
                        inactivity_timeout_seconds=self._settings.download_inactivity_timeout_seconds,
                        max_total_timeout_seconds=self._settings.download_max_total_timeout_seconds,
                    )
                    downloaded_path = self._downloader.download(
                        request,
                        on_progress=_on_progress,
                        cancel_event=cancel_event,
                        shutdown_event=self._shutdown_event,
                    )

                    if self._shutdown_event.is_set():
                        raise DownloadInterruptedError("Download interrupted by server shutdown.")
                    if cancel_event.is_set():
                        self._safe_unlink(downloaded_path)
                        raise DownloadCancelledError("Download cancelled by user.")

                    probe = self._validator.validate(
                        downloaded_path,
                        max_resolution=self._settings.download_max_resolution,
                        require_no_audio=not self._settings.download_audio_enabled,
                        cancel_event=cancel_event,
                        shutdown_event=self._shutdown_event,
                    )

                    with self._lock:
                        if cancel_event.is_set():
                            raise DownloadCancelledError("Download cancelled during validation.")
                        if self._shutdown_event.is_set():
                            raise DownloadInterruptedError("Validation interrupted by shutdown.")
                        self._repo.update_download_state(
                            video_id,
                            download_status=DownloadStatus.DOWNLOADED,
                            local_video_path=str(downloaded_path.resolve()),
                            actual_resolution=probe.resolution_label,
                            file_size_bytes=probe.file_size_bytes,
                            video_codec=probe.video_codec,
                            download_progress=100.0,
                            downloaded_bytes=probe.file_size_bytes,
                            total_bytes=probe.file_size_bytes,
                            download_requested=False,
                            download_completed_at=_utc_now(),
                            download_retry_count=attempt,
                            clear_error=True,
                        )
                    logger.info(
                        "Downloaded and verified video_id=%d (%s, %s, %s bytes)",
                        video_id,
                        probe.resolution_label,
                        probe.video_codec,
                        probe.file_size_bytes,
                    )
                    return

                except (DownloadCancelledError, DownloadInterruptedError):
                    raise
                except DownloadError as exc:
                    if exc.recoverable and attempt < max_retries:
                        attempt += 1
                        backoff = min(2**attempt, 30)
                        logger.warning(
                            "Transient download error for video_id=%d (attempt %d/%d): %s",
                            video_id,
                            attempt,
                            max_retries,
                            exc,
                        )
                        self._repo.update_download_state(
                            video_id,
                            download_status=DownloadStatus.DOWNLOADING,
                            download_retry_count=attempt,
                            download_error=str(exc),
                        )
                        if self._shutdown_event.wait(backoff):
                            raise DownloadInterruptedError(
                                "Download interrupted during retry backoff."
                            ) from exc
                        if cancel_event.is_set():
                            raise DownloadCancelledError(
                                "Download cancelled during retry."
                            ) from exc
                        continue

                    # Non-recoverable or retries exhausted. Clean up any invalid artifact.
                    self._cleanup_all_for_video(video.youtube_video_id)
                    self._repo.update_download_state(
                        video_id,
                        download_status=DownloadStatus.FAILED,
                        download_requested=False,
                        download_retry_count=attempt,
                        download_error=str(exc),
                    )
                    logger.error("Download failed for video_id=%d: %s", video_id, exc)
                    return

        except DownloadInterruptedError:
            # Preserve .part files and keep download_requested=True for automatic recovery.
            with self._lock:
                latest = self._live_progress.get(video_id)
            self._repo.update_download_state(
                video_id,
                download_status=DownloadStatus.DOWNLOADING,
                download_requested=True,
                download_progress=latest.progress_percent if latest else None,
                downloaded_bytes=latest.downloaded_bytes if latest else None,
                total_bytes=latest.total_bytes if latest else None,
            )
            logger.info("Preserved interrupted download state for video_id=%d", video_id)
        except DownloadCancelledError:
            self._cleanup_partial_files(video.youtube_video_id)
            self._repo.update_download_state(
                video_id,
                download_status=DownloadStatus.CANCELLED,
                download_requested=False,
                download_error="Download cancelled by user.",
            )
            logger.info("Download cancelled for video_id=%d", video_id)
        except Exception as exc:
            logger.exception("Unexpected failure in download worker for video_id=%d", video_id)
            self._repo.update_download_state(
                video_id,
                download_status=DownloadStatus.FAILED,
                download_requested=False,
                download_error=f"Unexpected download error: {exc}",
            )
        finally:
            with self._lock:
                self._active_videos.discard(video_id)
                self._cancel_events.pop(video_id, None)
                self._live_progress.pop(video_id, None)

    def _download_dir(self) -> Path:
        assert self._settings.download_dir is not None
        return self._settings.download_dir

    def _check_disk_space(self, required_extra_bytes: int = 0) -> None:
        dest_dir = self._download_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(dest_dir)
        min_bytes = self._settings.download_min_free_disk_mb * 1024 * 1024
        needed = min_bytes + max(0, required_extra_bytes)
        if usage.free < needed:
            free_mb = usage.free // (1024 * 1024)
            needed_mb = needed // (1024 * 1024)
            raise InsufficientDiskSpaceError(
                f"Insufficient disk space: {free_mb} MB free, {needed_mb} MB required."
            )

    def _has_valid_local_file(self, video: VideoEntity) -> bool:
        if not video.local_video_path:
            return False
        path = Path(video.local_video_path)
        return path.exists() and path.is_file() and path.stat().st_size > 0

    def _cleanup_partial_files(self, youtube_video_id: str) -> None:
        safe_id = sanitize_youtube_video_id(youtube_video_id)
        dest_dir = self._download_dir()
        if not dest_dir.exists():
            return
        for pattern in (f"{safe_id}.*.part*", f"{safe_id}.part*", f"{safe_id}.*.ytdl"):
            for candidate in dest_dir.glob(pattern):
                self._safe_unlink(candidate)

    def _cleanup_all_for_video(self, youtube_video_id: str) -> None:
        safe_id = sanitize_youtube_video_id(youtube_video_id)
        dest_dir = self._download_dir()
        if not dest_dir.exists():
            return
        for candidate in dest_dir.glob(f"{safe_id}.*"):
            self._safe_unlink(candidate)

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except OSError:
            pass
