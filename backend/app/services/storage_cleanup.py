"""Conservative retention for flat, job-owned extraction generations only."""

import logging
import os
import re
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.repositories.extractions import ExtractionState

logger = logging.getLogger(__name__)
_GENERATION = re.compile(r"^[0-9a-f]{32}$")
_INTERMEDIATE = re.compile(
    r"^(?:sample_\d+\.png|frame_\d+\.png|manifest\.json\.tmp|\.extraction\.lock)$"
)


@dataclass(frozen=True)
class _GenerationFiles:
    count: int
    size_bytes: int
    newest_mtime: float


@dataclass
class CleanupReport:
    dry_run: bool
    generations: int = 0
    files: int = 0
    bytes: int = 0
    errors: int = 0


class StorageCleanupService:
    """Use the owner's shared lock; no scheduler or deletion of source media.

    Open each directory without following symlinks. Deletion uses directory file
    descriptors so a renamed ancestor cannot redirect it outside managed storage.
    Unknown files and successful manifests conservatively protect a generation.
    """

    def __init__(
        self,
        root: Path,
        *,
        state: Callable[[int], ExtractionState],
        active: Callable[[int], bool],
        media_lock: threading.RLock,
        retention_hours: float = 48,
    ) -> None:
        self._root = root
        self._state = state
        self._active = active
        self._lock = media_lock
        self._retention_seconds = retention_hours * 3600

    def cleanup(self, *, dry_run: bool = False, now: float | None = None) -> CleanupReport:
        report = CleanupReport(dry_run=dry_run)
        cutoff = (time.time() if now is None else now) - self._retention_seconds
        with self._lock:
            try:
                root_fd = self._open(self._root)
                try:
                    self._scan(root_fd, cutoff, report)
                finally:
                    os.close(root_fd)
            except OSError:
                report.errors += 1
                logger.warning("Could not inspect managed frame storage", exc_info=True)
        logger.info(
            "Extraction cleanup dry_run=%s generations=%d files=%d bytes=%d errors=%d",
            report.dry_run,
            report.generations,
            report.files,
            report.bytes,
            report.errors,
        )
        return report

    @staticmethod
    def _open(path: str | Path, parent: int | None = None) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        if parent is not None:
            return os.open(path, flags, dir_fd=parent)
        absolute = Path(path).absolute()
        fd = os.open(absolute.anchor, flags)
        try:
            for component in absolute.parts[1:]:
                next_fd = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            return fd
        except OSError:
            os.close(fd)
            raise

    def _scan(self, root_fd: int, cutoff: float, report: CleanupReport) -> None:
        with os.scandir(root_fd) as videos:
            for video in videos:
                if not re.fullmatch(r"[1-9]\d*", video.name) or not video.is_dir(
                    follow_symlinks=False
                ):
                    continue
                video_id = int(video.name)
                state = self._state(video_id)
                if self._active(video_id) or state.requested or state.status == "extracting":
                    continue
                try:
                    video_fd = self._open(video.name, root_fd)
                    try:
                        self._video(video_fd, state, cutoff, report)
                    finally:
                        os.close(video_fd)
                except OSError:
                    report.errors += 1
                    logger.warning("Cleanup failed for video_id=%d", video_id, exc_info=True)

    def _video(
        self, video_fd: int, state: ExtractionState, cutoff: float, report: CleanupReport
    ) -> None:
        # Failed jobs retain their newest incomplete attempt for explicit retry/inspection.
        with os.scandir(video_fd) as entries:
            names = [
                e.name
                for e in entries
                if _GENERATION.fullmatch(e.name) and e.is_dir(follow_symlinks=False)
            ]
        candidates: list[tuple[str, float]] = []
        for name in names:
            fd = self._open(name, video_fd)
            try:
                files = self._intermediates(fd)
                if files is not None:
                    newest = max(os.fstat(fd).st_mtime, files.newest_mtime)
                    candidates.append((name, newest))
            finally:
                os.close(fd)
        recoverable = max(candidates, key=lambda item: item[1])[0] if candidates else None
        for name, newest in candidates:
            if newest >= cutoff or (state.status == "failed" and name == recoverable):
                continue
            if state.frame_directory and Path(state.frame_directory).name == name:
                continue
            fd = self._open(name, video_fd)
            try:
                files = self._intermediates(fd)
                if files is None:
                    continue
                if max(os.fstat(fd).st_mtime, files.newest_mtime) >= cutoff:
                    continue
                if report.dry_run:
                    report.files += files.count
                    report.bytes += files.size_bytes
                else:
                    with os.scandir(fd) as entries:
                        for entry in entries:
                            info = entry.stat(follow_symlinks=False)
                            os.unlink(entry.name, dir_fd=fd)
                            report.files += 1
                            report.bytes += info.st_size
                if not report.dry_run:
                    # Refuse to remove a replacement created by an external operator.
                    if (
                        os.stat(name, dir_fd=video_fd, follow_symlinks=False).st_ino
                        != os.fstat(fd).st_ino
                    ):
                        raise OSError("Generation changed during cleanup")
                    os.rmdir(name, dir_fd=video_fd)
                report.generations += 1
            finally:
                os.close(fd)

    @staticmethod
    def _intermediates(fd: int) -> _GenerationFiles | None:
        count = size_bytes = 0
        newest_mtime = 0.0
        with os.scandir(fd) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or not _INTERMEDIATE.fullmatch(entry.name):
                    return None
                count += 1
                size_bytes += info.st_size
                newest_mtime = max(newest_mtime, info.st_mtime)
        return _GenerationFiles(count, size_bytes, newest_mtime)
