"""Automated end-to-end pipeline orchestrator coordinating existing stage services."""

from __future__ import annotations

import contextlib
import logging
import shutil
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path

from app.core.config import Settings
from app.domain.downloads import (
    DownloadError,
    DownloadStatus,
    InsufficientDiskSpaceError,
)
from app.domain.exclusion import format_exclusion_reason
from app.domain.extraction import ExtractionError, ExtractionStatus
from app.domain.pdfs import PdfError
from app.domain.pipeline import (
    PipelineConflictError,
    PipelineRunPage,
    PipelineRunState,
    PipelineSettings,
    PipelineStage,
    PipelineTriggerType,
)
from app.domain.slides import SlideError
from app.domain.videos import LivestreamStatus, ProcessingStatus, VideoDiscoveryError, VideoEntity
from app.infrastructure.frame_extractor import read_manifest
from app.infrastructure.models import utc_now
from app.repositories.extractions import ExtractionRepository
from app.repositories.pdfs import PdfRepository
from app.repositories.pipeline import PipelineRepository
from app.repositories.settings import SettingsRepository
from app.repositories.slides import SlideRepository
from app.repositories.videos import VideoRepository
from app.services.discovery import DiscoveryService
from app.services.downloader import VideoDownloadService
from app.services.exclusion import VideoExclusionService
from app.services.extraction import ExtractionService
from app.services.imaging.pipeline import read_slide_manifest
from app.services.pdfs import PdfService
from app.services.pipeline_cleanup import PipelineCleanupService
from app.services.slides import SlideService

logger = logging.getLogger("app.services.pipeline")


class _RunCancelledError(Exception):
    """Internal signal that the pipeline run was cancelled or shutting down."""


class _VideoExcludedInStageError(Exception):
    """Raised when a video becomes excluded before or during a stage."""


class _VideoStageFailure(Exception):
    """Carries retryability metadata for a failed video stage."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class PipelineOrchestrator:
    """Coordinates discovery, eligibility, download, extraction, slides, PDF, and cleanup."""

    def __init__(
        self,
        *,
        settings: Settings,
        pipeline_repo: PipelineRepository,
        settings_repo: SettingsRepository,
        video_repo: VideoRepository,
        extraction_repo: ExtractionRepository,
        slide_repo: SlideRepository,
        pdf_repo: PdfRepository,
        exclusion_service: VideoExclusionService,
        download_service: VideoDownloadService,
        extraction_service: ExtractionService,
        slide_service: SlideService,
        pdf_service: PdfService,
        cleanup_service: PipelineCleanupService,
        discovery_factory: Callable[[], DiscoveryService | None],
    ) -> None:
        self._settings = settings
        self._repo = pipeline_repo
        self._settings_repo = settings_repo
        self._videos = video_repo
        self._extractions = extraction_repo
        self._slides = slide_repo
        self._pdfs = pdf_repo
        self._exclusion = exclusion_service
        self._downloader = download_service
        self._extractor = extraction_service
        self._slide_service = slide_service
        self._pdf_service = pdf_service
        self._cleanup = cleanup_service
        self._discovery_factory = discovery_factory

        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._cancel_events: dict[int, threading.Event] = {}
        self._run_futures: dict[int, Future[None]] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pipeline-run")

    def default_pipeline_settings(self) -> PipelineSettings:
        return PipelineSettings(
            scheduler_enabled=self._settings.scheduler_enabled,
            scheduler_frequency=self._settings.scheduler_frequency,
            scheduler_time=self._settings.scheduler_time,
            timezone=self._settings.timezone,
            discovery_lookback_days=self._settings.discovery_lookback_days,
            extraction_interval_seconds=self._settings.extraction_interval_seconds,
            pipeline_concurrent_limit=self._settings.pipeline_concurrent_limit,
            pipeline_retry_attempts=self._settings.pipeline_retry_attempts,
            auto_cleanup_enabled=self._settings.auto_cleanup_enabled,
            min_free_disk_mb=self._settings.pipeline_min_free_disk_mb,
        )

    def get_pipeline_settings(self) -> PipelineSettings:
        cfg, _ = self._settings_repo.get_pipeline_settings(self.default_pipeline_settings())
        return cfg

    def trigger_run(
        self,
        trigger_type: PipelineTriggerType = "manual",
        *,
        video_ids: list[int] | None = None,
        reprocess_existing: bool = False,
    ) -> PipelineRunState:
        with self._lock:
            if self._shutdown.is_set():
                raise PipelineConflictError("Pipeline orchestrator is shutting down.")
            run = self._repo.create_run(
                trigger_type=trigger_type,
                reprocess_existing=reprocess_existing,
                target_video_ids=video_ids,
            )
            self._submit_run(run.id)
            return self._repo.get_run(run.id)

    def _submit_run(self, run_id: int) -> None:
        cancel_event = threading.Event()
        self._cancel_events[run_id] = cancel_event
        future = self._executor.submit(self._execute_run, run_id, cancel_event)
        self._run_futures[run_id] = future

    def get_active_run(self) -> PipelineRunState | None:
        return self._repo.get_active_run()

    def get_run(self, run_id: int) -> PipelineRunState:
        return self._repo.get_run(run_id)

    def list_runs(self, *, page: int = 1, page_size: int = 20) -> PipelineRunPage:
        return self._repo.list_runs(page=page, page_size=page_size)

    def cancel_run(self, run_id: int) -> PipelineRunState:
        with self._lock:
            run = self._repo.get_run(run_id)
            if run.status not in {"queued", "running"}:
                raise PipelineConflictError(f"Pipeline run #{run_id} is already {run.status}.")
            event = self._cancel_events.get(run_id)
            if event is not None:
                event.set()
            if run.current_video_id is not None:
                self._cancel_active_video_stages(run.current_video_id)
            self._repo.append_log(run_id, "Cancellation requested by user.", level="WARNING")
            if event is None:
                # Run was not actively executing in memory (e.g. stale).
                return self._repo.update_run(
                    run_id,
                    status="cancelled",
                    completed_at=utc_now(),
                    current_stage="idle",
                )
            return self._repo.get_run(run_id)

    def retry_failed_run(self, run_id: int) -> PipelineRunState:
        source_run = self._repo.get_run(run_id)
        failed_ids = [v.video_id for v in source_run.videos if v.status == "failed"]
        if not failed_ids:
            raise PipelineConflictError(f"Pipeline run #{run_id} has no failed videos to retry.")
        return self.trigger_run(
            "manual",
            video_ids=failed_ids,
            reprocess_existing=source_run.reprocess_existing,
        )

    def recover(self) -> int:
        """Resume any incomplete runs after application restart without duplicating work."""
        recoverable = self._repo.list_recoverable_runs()
        resumed = 0
        for run in recoverable:
            with self._lock:
                if run.id in self._cancel_events or self._shutdown.is_set():
                    continue
                self._repo.append_log(
                    run.id,
                    "Resuming interrupted pipeline run after application restart.",
                    level="WARNING",
                )
                self._submit_run(run.id)
                resumed += 1
        return resumed

    def shutdown(self) -> None:
        self._shutdown.set()
        with self._lock:
            for event in self._cancel_events.values():
                event.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    # Internal orchestration
    # ------------------------------------------------------------------

    def _cancel_active_video_stages(self, video_id: int) -> None:
        for fn in (
            lambda: self._downloader.cancel_download(video_id),
            lambda: self._extractor.cancel(video_id),
            lambda: self._slide_service.cancel(video_id),
            lambda: self._pdf_service.cancel(video_id),
        ):
            with contextlib.suppress(Exception):
                fn()

    def _check_cancelled(self, cancel_event: threading.Event) -> None:
        if cancel_event.is_set() or self._shutdown.is_set():
            raise _RunCancelledError("Pipeline run cancelled.")

    def _check_disk_space(self, min_free_mb: int) -> None:
        if min_free_mb <= 0:
            return
        target = self._settings.storage_dir
        target.mkdir(parents=True, exist_ok=True)
        free_mb = shutil.disk_usage(target).free / (1024 * 1024)
        if free_mb < min_free_mb:
            raise InsufficientDiskSpaceError(
                f"Critically low disk space: {free_mb:.1f} MB free, "
                f"minimum required is {min_free_mb} MB."
            )

    def _execute_run(self, run_id: int, cancel_event: threading.Event) -> None:
        try:
            cfg = self.get_pipeline_settings()
            self._repo.update_run(run_id, status="running", last_error=None)
            self._repo.append_log(
                run_id,
                f"Pipeline run #{run_id} started (concurrency={cfg.pipeline_concurrent_limit}, "
                f"auto_cleanup={cfg.auto_cleanup_enabled}).",
            )
            run = self._repo.get_run(run_id)

            # Stage 1: Discovery (only when no explicit target_video_ids were provided).
            if not run.target_video_ids:
                self._check_cancelled(cancel_event)
                self._run_discovery_stage(run_id, cfg)

            # Stage 2: Evaluate eligibility.
            self._check_cancelled(cancel_event)
            eligible_ids = self._run_evaluation_stage(run_id, run, cfg)

            # Stages 3-8: Process eligible videos using bounded concurrency.
            if eligible_ids:
                self._process_eligible_videos(run_id, eligible_ids, cfg, cancel_event)

            # Finalize status.
            final_run = self._repo.sync_run_counts(run_id)
            if cancel_event.is_set() and not self._shutdown.is_set():
                self._repo.update_run(
                    run_id,
                    status="cancelled",
                    current_stage="idle",
                    current_video_id=None,
                    current_video_title=None,
                    current_stage_progress=0.0,
                    completed_at=utc_now(),
                )
                self._repo.append_log(run_id, "Pipeline run cancelled.", level="WARNING")
            elif self._shutdown.is_set():
                # Leave status as running so startup recovery resumes it.
                self._repo.append_log(
                    run_id,
                    "Pipeline run paused on shutdown; will resume on restart.",
                    level="WARNING",
                )
            elif final_run.failed_videos > 0:
                status = "completed_with_errors" if final_run.completed_videos > 0 else "failed"
                self._repo.update_run(
                    run_id,
                    status=status,
                    current_stage="completed",
                    current_video_id=None,
                    current_video_title=None,
                    current_stage_progress=100.0,
                    completed_at=utc_now(),
                )
                self._repo.append_log(
                    run_id,
                    f"Pipeline run finished with {final_run.failed_videos} failed video(s).",
                    level="WARNING",
                )
            else:
                self._repo.update_run(
                    run_id,
                    status="completed",
                    current_stage="completed",
                    current_video_id=None,
                    current_video_title=None,
                    current_stage_progress=100.0,
                    completed_at=utc_now(),
                )
                self._repo.append_log(run_id, f"Pipeline run #{run_id} completed successfully.")
        except _RunCancelledError:
            if not self._shutdown.is_set():
                self._repo.sync_run_counts(run_id)
                self._repo.update_run(
                    run_id,
                    status="cancelled",
                    current_stage="idle",
                    current_video_id=None,
                    current_video_title=None,
                    completed_at=utc_now(),
                )
                self._repo.append_log(run_id, "Pipeline run cancelled.", level="WARNING")
        except Exception as exc:
            logger.exception("Pipeline run #%d failed unexpectedly", run_id)
            self._repo.update_run(
                run_id,
                status="failed",
                current_stage="idle",
                last_error=str(exc),
                completed_at=utc_now(),
            )
            self._repo.append_log(run_id, f"Pipeline run failed: {exc}", level="ERROR")
        finally:
            with self._lock:
                self._cancel_events.pop(run_id, None)
                self._run_futures.pop(run_id, None)

    def _run_discovery_stage(self, run_id: int, cfg: PipelineSettings) -> None:
        self._repo.update_run(run_id, current_stage="discovering", current_stage_progress=0.0)
        discovery = self._discovery_factory()
        if discovery is None:
            self._repo.append_log(
                run_id,
                "YOUTUBE_API_KEY is not configured; skipping discovery stage.",
                level="WARNING",
                stage="discovering",
            )
            return
        try:
            summary = discovery.discover_all_channels(lookback_days=cfg.discovery_lookback_days)
            self._repo.append_log(
                run_id,
                f"Discovery checked {summary.channels_checked} channel(s): "
                f"found {summary.videos_found}, added {summary.new_videos_added}, "
                f"skipped {summary.existing_videos_skipped}.",
                stage="discovering",
            )
            if summary.errors:
                self._repo.update_run(run_id, last_error="; ".join(summary.errors[:3]))
        except VideoDiscoveryError as exc:
            self._repo.update_run(run_id, last_error=str(exc))
            self._repo.append_log(
                run_id,
                f"Discovery failed (continuing with existing videos): {exc}",
                level="WARNING",
                stage="discovering",
            )

    def _run_evaluation_stage(
        self, run_id: int, run: PipelineRunState, cfg: PipelineSettings
    ) -> list[int]:
        self._repo.update_run(run_id, current_stage="evaluating", current_stage_progress=0.0)
        self._exclusion.reevaluate_all_videos()

        existing_by_vid = {v.video_id: v for v in self._repo.get_run_videos(run_id)}

        if run.target_video_ids:
            candidates = [
                v for vid in run.target_video_ids if (v := self._videos.get_by_id(vid)) is not None
            ]
        else:
            candidates = self._videos.list_pipeline_candidates(
                min_duration_seconds=self._settings.discovery_min_duration_seconds
            )

        eligible_ids: list[int] = []
        for video in candidates:
            existing = existing_by_vid.get(video.id)
            if existing is not None and existing.status in {"completed", "excluded", "skipped"}:
                continue

            self._repo.ensure_run_video(
                run_id,
                video_id=video.id,
                video_title=video.title,
                youtube_video_id=video.youtube_video_id,
            )

            if video.is_excluded:
                self._repo.update_run_video(
                    run_id,
                    video.id,
                    status="excluded",
                    current_stage="evaluating",
                    error=format_exclusion_reason(video.excluded_keywords),
                    is_retryable=False,
                    completed_at=utc_now(),
                )
                continue

            if video.livestream_status in {LivestreamStatus.UPCOMING, LivestreamStatus.LIVE}:
                self._repo.update_run_video(
                    run_id,
                    video.id,
                    status="skipped",
                    current_stage="evaluating",
                    error=f"Skipped {video.livestream_status.value} livestream.",
                    completed_at=utc_now(),
                )
                continue

            if not run.reprocess_existing and self._has_valid_completed_pdf(video.id):
                self._repo.update_run_video(
                    run_id,
                    video.id,
                    status="skipped",
                    current_stage="evaluating",
                    error="Valid completed PDF already exists.",
                    completed_at=utc_now(),
                )
                continue

            eligible_ids.append(video.id)

        self._repo.sync_run_counts(run_id)
        self._repo.append_log(
            run_id,
            f"Evaluation complete: {len(eligible_ids)} video(s) queued for processing.",
            stage="evaluating",
        )
        return eligible_ids

    def _has_valid_completed_pdf(self, video_id: int) -> bool:
        try:
            self._cleanup.validate_video_pdf(video_id)
            return True
        except PdfError:
            return False

    def _process_eligible_videos(
        self,
        run_id: int,
        video_ids: list[int],
        cfg: PipelineSettings,
        cancel_event: threading.Event,
    ) -> None:
        with ThreadPoolExecutor(
            max_workers=cfg.pipeline_concurrent_limit,
            thread_name_prefix=f"pipeline-v-{run_id}",
        ) as pool:
            pending_futures: list[tuple[int, Future[None]]] = []
            for video_id in video_ids:
                self._check_cancelled(cancel_event)
                try:
                    self._check_disk_space(cfg.min_free_disk_mb)
                except InsufficientDiskSpaceError as exc:
                    self._repo.update_run(run_id, last_error=str(exc))
                    self._repo.append_log(
                        run_id,
                        f"Stopping additional video work: {exc}",
                        level="ERROR",
                    )
                    self._repo.update_run_video(
                        run_id,
                        video_id,
                        status="failed",
                        error=str(exc),
                        is_retryable=True,
                        completed_at=utc_now(),
                    )
                    continue
                pending_futures.append(
                    (
                        video_id,
                        pool.submit(
                            self._process_video_with_retries,
                            run_id,
                            video_id,
                            cfg,
                            cancel_event,
                        ),
                    )
                )

            for _vid, fut in pending_futures:
                while not cancel_event.is_set() and not self._shutdown.is_set():
                    try:
                        fut.result(timeout=0.5)
                        break
                    except FutureTimeoutError:
                        continue
                if cancel_event.is_set() or self._shutdown.is_set():
                    fut.cancel()

    def _process_video_with_retries(
        self,
        run_id: int,
        video_id: int,
        cfg: PipelineSettings,
        cancel_event: threading.Event,
    ) -> None:
        self._check_cancelled(cancel_event)
        max_attempts = cfg.pipeline_retry_attempts + 1
        attempt = 0
        while attempt < max_attempts:
            self._check_cancelled(cancel_event)
            try:
                self._process_single_video(run_id, video_id, cfg, cancel_event)
                self._repo.sync_run_counts(run_id)
                return
            except _RunCancelledError:
                self._repo.update_run_video(
                    run_id,
                    video_id,
                    status="cancelled",
                    completed_at=utc_now(),
                )
                self._repo.sync_run_counts(run_id)
                return
            except _VideoExcludedInStageError as exc:
                self._repo.update_run_video(
                    run_id,
                    video_id,
                    status="excluded",
                    error=str(exc),
                    is_retryable=False,
                    completed_at=utc_now(),
                )
                self._repo.append_log(
                    run_id, str(exc), level="WARNING", video_id=video_id, stage="evaluating"
                )
                self._repo.sync_run_counts(run_id)
                return
            except _VideoStageFailure as exc:
                attempt += 1
                if not exc.retryable or attempt >= max_attempts:
                    self._repo.update_run(run_id, last_error=str(exc))
                    self._repo.update_run_video(
                        run_id,
                        video_id,
                        status="failed",
                        retry_count=attempt,
                        is_retryable=exc.retryable,
                        error=str(exc),
                        completed_at=utc_now(),
                    )
                    self._videos.update_processing_status(video_id, ProcessingStatus.FAILED)
                    self._repo.append_log(
                        run_id,
                        f"Video failed permanently: {exc}",
                        level="ERROR",
                        video_id=video_id,
                    )
                    self._repo.sync_run_counts(run_id)
                    return
                backoff = min(30, 2**attempt)
                self._repo.update_run_video(
                    run_id,
                    video_id,
                    retry_count=attempt,
                    error=f"Retrying ({attempt}/{cfg.pipeline_retry_attempts}): {exc}",
                )
                self._repo.append_log(
                    run_id,
                    f"Retryable error (attempt {attempt}/{cfg.pipeline_retry_attempts}), "
                    f"waiting {backoff}s: {exc}",
                    level="WARNING",
                    video_id=video_id,
                )
                cancel_event.wait(backoff)

    def _assert_not_excluded(self, video_id: int) -> VideoEntity:
        video = self._videos.get_by_id(video_id)
        if video is None:
            raise _VideoStageFailure(f"Video {video_id} not found.", retryable=False)
        if video.is_excluded:
            raise _VideoExcludedInStageError(format_exclusion_reason(video.excluded_keywords))
        return video

    def _update_stage(
        self,
        run_id: int,
        video: VideoEntity,
        stage: PipelineStage,
        progress: float = 0.0,
    ) -> None:
        self._repo.update_run(
            run_id,
            current_stage=stage,
            current_video_id=video.id,
            current_video_title=video.title,
            current_stage_progress=progress,
        )
        self._repo.update_run_video(
            run_id,
            video.id,
            status="running",
            current_stage=stage,
            stage_progress=progress,
        )

    def _wait_future(
        self,
        future: Future[None] | None,
        cancel_event: threading.Event,
        *,
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        if future is None:
            return
        while not future.done():
            self._check_cancelled(cancel_event)
            try:
                future.result(timeout=0.5)
                return
            except FutureTimeoutError:
                if on_tick is not None:
                    on_tick()
        future.result()

    def _process_single_video(
        self,
        run_id: int,
        video_id: int,
        cfg: PipelineSettings,
        cancel_event: threading.Event,
    ) -> None:
        video = self._assert_not_excluded(video_id)
        self._repo.update_run_video(
            run_id, video_id, status="running", started_at=utc_now(), error=None
        )
        self._videos.update_processing_status(video_id, ProcessingStatus.RUNNING)

        # Stage 3: Download
        video = self._assert_not_excluded(video_id)
        self._check_disk_space(cfg.min_free_disk_mb)
        self._update_stage(run_id, video, "downloading", 0.0)
        if not self._has_valid_download(video):
            try:
                self._downloader.start_download(video_id)
            except DownloadError as exc:
                is_retryable = isinstance(exc, InsufficientDiskSpaceError) or exc.recoverable
                raise _VideoStageFailure(str(exc), retryable=is_retryable) from exc
            self._wait_future(
                self._downloader.get_future(video_id),
                cancel_event,
                on_tick=lambda: self._update_stage(
                    run_id,
                    video,
                    "downloading",
                    self._downloader.get_progress(video_id).progress_percent,
                ),
            )
            refreshed = self._assert_not_excluded(video_id)
            if refreshed.download_status != DownloadStatus.DOWNLOADED:
                err = (
                    refreshed.download_error
                    or f"Download ended in state {refreshed.download_status}"
                )
                raise _VideoStageFailure(err, retryable=True)

        # Stage 4: Extract screenshots
        video = self._assert_not_excluded(video_id)
        self._check_disk_space(cfg.min_free_disk_mb)
        self._update_stage(run_id, video, "extracting", 0.0)
        if not self._has_valid_extraction(video_id):
            try:
                self._extractor.start(video_id, interval=cfg.extraction_interval_seconds)
            except (ExtractionError, DownloadError) as exc:
                raise _VideoStageFailure(str(exc), retryable=True) from exc
            self._wait_future(
                self._extractor.get_future(video_id),
                cancel_event,
                on_tick=lambda: self._update_stage(
                    run_id,
                    video,
                    "extracting",
                    self._extractions.get(video_id).progress,
                ),
            )
            ext_state = self._extractions.get(video_id)
            if ext_state.status == ExtractionStatus.CANCELLED:
                raise _RunCancelledError("Extraction cancelled.")
            if ext_state.status != ExtractionStatus.EXTRACTED:
                raise _VideoStageFailure(
                    ext_state.error or f"Extraction ended in state {ext_state.status}",
                    retryable=True,
                )

        # Stage 5: Process screenshots
        video = self._assert_not_excluded(video_id)
        self._check_disk_space(cfg.min_free_disk_mb)
        self._update_stage(run_id, video, "processing_slides", 0.0)
        if not self._has_valid_slides(video_id):
            try:
                self._slide_service.start(video_id)
            except (SlideError, ExtractionError) as exc:
                raise _VideoStageFailure(str(exc), retryable=True) from exc
            self._wait_future(
                self._slide_service.get_future(video_id),
                cancel_event,
                on_tick=lambda: self._update_stage(
                    run_id,
                    video,
                    "processing_slides",
                    self._slides.get(video_id).progress,
                ),
            )
            slide_state = self._slides.get(video_id)
            if slide_state.status == "cancelled":
                raise _RunCancelledError("Slide processing cancelled.")
            if slide_state.status != "processed":
                raise _VideoStageFailure(
                    slide_state.error or f"Slide processing ended in state {slide_state.status}",
                    retryable=True,
                )

        slide_dir = self._slide_service.directory(video_id)
        slide_generation = slide_dir.name

        # Stage 6: Generate PDF
        video = self._assert_not_excluded(video_id)
        self._check_disk_space(cfg.min_free_disk_mb)
        self._update_stage(run_id, video, "generating_pdf", 0.0)
        if not self._has_valid_pdf_for_generation(video_id, slide_generation):
            try:
                self._pdf_service.start(video_id, regenerate=True)
            except (PdfError, SlideError) as exc:
                raise _VideoStageFailure(str(exc), retryable=True) from exc
            self._wait_future(
                self._pdf_service.get_future(video_id),
                cancel_event,
                on_tick=lambda: self._update_stage(
                    run_id,
                    video,
                    "generating_pdf",
                    self._pdfs.get(video_id).progress,
                ),
            )
            pdf_state = self._pdfs.get(video_id)
            if pdf_state.status == "cancelled":
                raise _RunCancelledError("PDF generation cancelled.")
            if pdf_state.status != "generated":
                raise _VideoStageFailure(
                    pdf_state.error or f"PDF generation ended in state {pdf_state.status}",
                    retryable=True,
                )

        # Stage 7: Validate generated PDF
        video = self._assert_not_excluded(video_id)
        self._update_stage(run_id, video, "validating_pdf", 50.0)
        try:
            self._cleanup.validate_video_pdf(video_id, expected_slide_generation=slide_generation)
        except PdfError as exc:
            raise _VideoStageFailure(f"PDF validation failed: {exc}", retryable=True) from exc

        # Stage 8: Clean intermediate files
        cleaned = False
        if cfg.auto_cleanup_enabled:
            self._update_stage(run_id, video, "cleaning", 50.0)
            try:
                result = self._cleanup.cleanup_video_intermediates(
                    video_id, expected_slide_generation=slide_generation
                )
                cleaned = result.cleaned
                self._repo.append_log(
                    run_id,
                    f"Cleaned {result.deleted_files} intermediate file(s) "
                    f"({result.freed_bytes} bytes) for '{video.title}'.",
                    video_id=video_id,
                    stage="cleaning",
                )
            except PdfError as exc:
                raise _VideoStageFailure(f"Cleanup failed: {exc}", retryable=True) from exc

        self._videos.update_processing_status(video_id, ProcessingStatus.SUCCEEDED)
        self._repo.update_run_video(
            run_id,
            video_id,
            status="completed",
            current_stage="completed",
            stage_progress=100.0,
            cleaned=cleaned,
            error=None,
            completed_at=utc_now(),
        )
        self._repo.append_log(
            run_id,
            f"Completed pipeline for '{video.title}'.",
            video_id=video_id,
            stage="completed",
        )

    def _has_valid_download(self, video: VideoEntity) -> bool:
        if video.download_status != DownloadStatus.DOWNLOADED or not video.local_video_path:
            return False
        path = Path(video.local_video_path)
        return path.is_file() and path.stat().st_size > 0

    def _has_valid_extraction(self, video_id: int) -> bool:
        state = self._extractions.get(video_id)
        if state.status != ExtractionStatus.EXTRACTED or not state.frame_directory:
            return False
        try:
            read_manifest(Path(state.frame_directory))
            return True
        except ExtractionError:
            return False

    def _has_valid_slides(self, video_id: int) -> bool:
        state = self._slides.get(video_id)
        if state.status != "processed" or not state.output_directory:
            return False
        try:
            read_slide_manifest(Path(state.output_directory), validate_images=False)
            return True
        except SlideError:
            return False

    def _has_valid_pdf_for_generation(self, video_id: int, slide_generation: str) -> bool:
        try:
            self._cleanup.validate_video_pdf(video_id, expected_slide_generation=slide_generation)
            return True
        except PdfError:
            return False
