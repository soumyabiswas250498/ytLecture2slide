"""Single-owner slide jobs, recovery, cancellation and safe output lifecycle."""

import errno
import logging
import re
import shutil
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import cv2

from app.core.config import Settings
from app.domain.downloads import DownloadError, VideoNotFoundError
from app.domain.exclusion import VideoExcludedError, format_exclusion_reason
from app.domain.extraction import ExtractionCancelled, ExtractionError
from app.domain.slides import (
    SlideConfig,
    SlideConflict,
    SlideError,
    SlideManifest,
    SlideState,
)
from app.infrastructure.frame_extractor import read_manifest
from app.repositories.slides import ChannelBoardProfileRepository, SlideRepository
from app.repositories.videos import VideoRepository
from app.services.extraction import ExtractionService, _StopSignal
from app.services.imaging.pipeline import SlideProcessor, read_slide_manifest
from app.services.storage_cleanup import StorageCleanupService

logger = logging.getLogger(__name__)


class SlideService:
    def __init__(
        self,
        *,
        videos: VideoRepository,
        repository: SlideRepository,
        extraction: ExtractionService,
        processor: SlideProcessor,
        settings: Settings,
        media_lock: threading.RLock,
        board_profiles: ChannelBoardProfileRepository | None = None,
    ) -> None:
        self.videos = videos
        self.repository = repository
        self.board_profiles = board_profiles
        self.extraction = extraction
        self.processor = processor
        self.settings = settings
        self.lock = media_lock
        self.events: dict[int, threading.Event] = {}
        self.stopping = threading.Event()
        assert settings.temp_dir is not None
        self.root = settings.temp_dir / "slides"
        self.pool = ThreadPoolExecutor(
            max_workers=settings.slide_concurrent_limit, thread_name_prefix="slides"
        )

    def state(self, video_id: int) -> SlideState:
        if self.videos.get_by_id(video_id) is None:
            raise VideoNotFoundError("Video not found.")
        return self.repository.get(video_id)

    def assert_inactive(self, video_id: int) -> None:
        state = self.repository.get(video_id)
        if video_id in self.events or state.requested or state.status == "processing":
            raise SlideConflict("Slide processing is queued or active for this video.")

    def assert_no_published_slides(self, video_id: int) -> None:
        self.assert_inactive(video_id)
        state = self.repository.get(video_id)
        if state.output_directory:
            raise SlideConflict(
                "Extracted frames are referenced by published slides; delete slides first."
            )

    def start(
        self,
        video_id: int,
        config: SlideConfig | None = None,
        *,
        retry: bool = False,
        reprocess: bool = False,
        save_channel_profile: bool = True,
    ) -> SlideState:
        with self.lock:
            if self.stopping.is_set():
                raise SlideConflict("Slide processor is shutting down.")
            state = self.state(video_id)
            video = self.videos.get_by_id(video_id)
            if video is not None and video.is_excluded:
                raise VideoExcludedError(
                    format_exclusion_reason(video.excluded_keywords),
                    video.excluded_keywords,
                )
            self.assert_inactive(video_id)
            self.extraction.assert_inactive(video_id)
            directory = self.extraction.directory(video_id)
            inputs = read_manifest(directory)
            if retry and state.status not in {"failed", "cancelled"}:
                raise SlideConflict("Only failed or cancelled processing can be retried.")
            if state.output_directory and not (retry or reprocess):
                raise SlideConflict("Slides already exist; explicitly request reprocessing.")
            base = (
                SlideConfig.model_validate_json(state.configuration)
                if retry
                else self.settings.slide_processing
            )
            if config is not None:
                overrides = base.model_dump()
                overrides.update(config.model_dump(exclude_unset=True))
                config = SlideConfig.model_validate(overrides)
            else:
                config = base
            # Full-frame processing policy: ignore any crop, perspective, or profile fields.
            config = config.model_copy(
                update={
                    "crop": None,
                    "corners": None,
                    "profile_crop": None,
                    "profile_reference_aspect": None,
                }
            )
            self.root.mkdir(parents=True, exist_ok=True)
            self._directory(video_id)
            if shutil.disk_usage(self.root).free < config.min_free_disk_mb * 1024 * 1024:
                raise SlideError("Insufficient disk space for slides.")
            claimed = self.repository.claim(video_id, config)
            claimed = self.repository.save(video_id, input_count=inputs.frame_count)
            self._enqueue(claimed)
            return claimed

    def _enqueue(self, state: SlideState) -> None:
        event = threading.Event()
        self.events[state.video_id] = event
        future = self.pool.submit(self._run, state, event)
        future.add_done_callback(lambda result: self._report(state.video_id, result))

    def _report(self, video_id: int, future: Future[None]) -> None:
        if not future.cancelled() and (error := future.exception()) is not None:
            logger.error(
                "Slide worker failure",
                extra={"job_id": f"slides:{video_id}"},
                exc_info=(type(error), error, error.__traceback__),
            )
            with self.lock:
                state = self.repository.get(video_id)
                if state.requested and not self.stopping.is_set():
                    self.repository.save(
                        video_id,
                        status="failed",
                        requested=False,
                        error="Unexpected slide worker failure; check logs and retry.",
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
                if state.retry_count >= self.settings.slide_retry_attempts:
                    self.repository.save(
                        state.video_id,
                        status="failed",
                        requested=False,
                        error="Slide recovery retry limit exceeded.",
                    )
                    continue
                state = self.repository.save(
                    state.video_id, status="pending", retry_count=state.retry_count + 1
                )
                self._enqueue(state)

    def cancel(self, video_id: int) -> SlideState:
        with self.lock:
            state = self.state(video_id)
            if not state.requested:
                raise SlideConflict("No active slide processing.")
            if event := self.events.get(video_id):
                event.set()
            return self.repository.save(
                video_id,
                status="cancelled",
                requested=False,
                error="Slide processing cancelled by user.",
            )

    def _directory(self, video_id: int) -> Path:
        path = self.root / str(video_id)
        if (
            self.root.is_symlink()
            or path.is_symlink()
            or path.resolve().parent != self.root.resolve()
        ):
            raise SlideError("Unsafe slide directory.")
        return path

    def directory(self, video_id: int) -> Path:
        state = self.state(video_id)
        if not state.output_directory:
            raise SlideConflict("No successful slide generation.")
        path = Path(state.output_directory)
        parent = self._directory(video_id)
        if (
            path.is_symlink()
            or path.resolve().parent != parent.resolve()
            or not re.fullmatch(r"[a-f0-9]{32}", path.name)
        ):
            raise SlideError("Unsafe slide generation.")
        return path

    def manifest(self, video_id: int) -> SlideManifest:
        return read_slide_manifest(self.directory(video_id), validate_images=False)

    def delete(self, video_id: int) -> SlideState:
        with self.lock:
            self.state(video_id)
            self.assert_inactive(video_id)
            directory = self._directory(video_id)
            if directory.exists():
                # Refuse symlink ancestors using the existing no-follow directory utility.
                fd = StorageCleanupService._open(directory)
                try:
                    if not shutil.rmtree.avoids_symlink_attacks:
                        raise SlideError("Safe recursive deletion is unavailable on this platform.")
                    for entry in directory.iterdir():
                        if not re.fullmatch(r"[a-f0-9]{32}", entry.name) or entry.is_symlink():
                            raise SlideError("Unknown or unsafe processed-output entry; preserved.")
                    for entry in directory.iterdir():
                        shutil.rmtree(entry.name, dir_fd=fd)
                finally:
                    import os

                    os.close(fd)
            return self.repository.save(
                video_id,
                status="pending",
                requested=False,
                progress=0,
                input_count=0,
                completed_count=0,
                additional_count=0,
                output_count=0,
                duplicate_count=0,
                reconstructed_count=0,
                review_count=0,
                output_directory=None,
                error=None,
                retry_count=0,
            )

    def shutdown(self) -> None:
        self.stopping.set()
        self.pool.shutdown(wait=True, cancel_futures=True)

    def _run(self, state: SlideState, event: threading.Event) -> None:
        video_id = state.video_id
        signal = _StopSignal(event, self.stopping)

        def progress(done: int, total: int, additional: int) -> None:
            with self.lock:
                if not signal.is_set():
                    self.repository.save(
                        video_id,
                        completed_count=done,
                        input_count=total,
                        additional_count=additional,
                        progress=min(99.9, done / total * 100),
                    )

        try:
            config = SlideConfig.model_validate_json(state.configuration)
            attempt = state.retry_count
            while True:
                try:
                    if signal.is_set():
                        raise ExtractionCancelled("Slide processing interrupted.")
                    with self.lock:
                        self.repository.save(
                            video_id,
                            status="processing",
                            completed_count=0,
                            additional_count=0,
                            progress=0,
                        )
                    frames = self.extraction.directory(video_id)
                    video = self.videos.get_by_id(video_id)
                    source = (
                        Path(video.local_video_path) if video and video.local_video_path else None
                    )
                    if source:
                        assert self.settings.download_dir is not None
                        if source.is_symlink() or not source.resolve().is_relative_to(
                            self.settings.download_dir
                        ):
                            raise SlideError("Unsafe source video path.")
                    output = self._directory(video_id) / uuid4().hex
                    result = self.processor.process(
                        frames,
                        output,
                        video_id=video_id,
                        config=config,
                        source=source,
                        cancel=signal,
                        on_progress=progress,
                    )
                    break
                except OSError as exc:
                    if (
                        exc.errno not in {errno.EAGAIN, errno.EBUSY, errno.EINTR}
                        or attempt >= self.settings.slide_retry_attempts
                    ):
                        raise
                    attempt += 1
                    self.repository.save(video_id, retry_count=attempt)
                    deadline = time.monotonic() + min(2**attempt, 30)
                    while time.monotonic() < deadline:
                        if event.wait(0.1) or self.stopping.is_set():
                            raise ExtractionCancelled("Slide retry interrupted.") from exc
            with self.lock:
                if signal.is_set():
                    raise ExtractionCancelled("Slide publication interrupted.")
                self.repository.save(
                    video_id,
                    status="processed",
                    requested=False,
                    progress=100,
                    output_directory=str(output),
                    output_count=len(result.slides),
                    duplicate_count=result.duplicate_count,
                    reconstructed_count=sum(
                        s.reconstruction_method != "original" for s in result.slides
                    ),
                    review_count=sum(s.manual_review for s in result.slides),
                    error=None,
                )
            logger.info("Slide generation published", extra={"job_id": f"slides:{video_id}"})
        except ExtractionCancelled:
            with self.lock:
                if not event.is_set():
                    self.repository.save(
                        video_id,
                        status="pending",
                        requested=True,
                        error="Interrupted by shutdown; awaiting recovery.",
                    )
        except (ExtractionError, DownloadError, OSError, ValueError, cv2.error):
            logger.exception("Slide processing failed", extra={"job_id": f"slides:{video_id}"})
            with self.lock:
                if not event.is_set():
                    self.repository.save(
                        video_id,
                        status="failed",
                        requested=False,
                        error=(
                            "Slide processing failed. Check image integrity, source video, "
                            "disk space and server logs; then retry."
                        ),
                    )
        finally:
            with self.lock:
                self.events.pop(video_id, None)
