"""Offline regression coverage for conservative cleanup and probe lifecycle."""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.domain.downloads import (
    DownloadCancelledError,
    DownloadInterruptedError,
    MediaValidationError,
)
from app.infrastructure.media_probe import FFprobeValidator
from app.infrastructure.processes import capture_process, terminate_process
from app.infrastructure.ytdlp_downloader import YtDlpVideoDownloader
from app.repositories.extractions import ExtractionState
from app.services.storage_cleanup import StorageCleanupService


@pytest.fixture
def cleanup(tmp_path: Path) -> StorageCleanupService:
    root = tmp_path / "frames"
    root.mkdir()
    return StorageCleanupService(
        root,
        state=lambda video_id: ExtractionState(video_id=video_id),
        active=lambda _: False,
        media_lock=threading.RLock(),
    )


def generation(root: Path, *, video: int = 1, name: str = "a" * 32, age: int = 49) -> Path:
    directory = root / str(video) / name
    directory.mkdir(parents=True)
    frame = directory / "sample_000000001.png"
    frame.write_bytes(b"interrupted-png")
    old = time.time() - age * 3600
    os.utime(frame, (old, old))
    os.utime(directory, (old, old))
    return directory


def test_cleanup_dry_run_and_expired_files(cleanup: StorageCleanupService) -> None:
    directory = generation(cleanup._root)
    expected = (directory / "sample_000000001.png").stat().st_size
    preview = cleanup.cleanup(dry_run=True)
    assert (preview.generations, preview.files, preview.bytes, preview.errors) == (
        1,
        1,
        expected,
        0,
    )
    assert directory.exists()
    actual = cleanup.cleanup()
    assert (actual.generations, actual.files, actual.bytes, actual.errors) == (1, 1, expected, 0)
    assert not directory.exists()
    assert cleanup.cleanup().files == 0


@pytest.mark.parametrize(
    "protection", ["active", "requested", "extracting", "success", "referenced", "recent"]
)
def test_cleanup_preserves_protected_generations(
    cleanup: StorageCleanupService, protection: str
) -> None:
    directory = generation(cleanup._root, age=1 if protection == "recent" else 49)
    state = ExtractionState(video_id=1)
    if protection == "active":
        cleanup._active = lambda _: True
    elif protection == "requested":
        state.requested = True
    elif protection == "extracting":
        state.status = "extracting"  # type: ignore[assignment]
    elif protection == "success":
        (directory / "manifest.json").write_text("even invalid publication is preserved")
        old = time.time() - 100 * 3600
        os.utime(directory / "manifest.json", (old, old))
        os.utime(directory, (old, old))
    elif protection == "referenced":
        state.frame_directory = str(directory)
    cleanup._state = lambda _: state
    assert cleanup.cleanup().generations == 0
    assert directory.exists()


def test_cleanup_preserves_recoverable_attempt_and_discards_older(
    cleanup: StorageCleanupService,
) -> None:
    older = generation(cleanup._root, name="b" * 32, age=100)
    newest = generation(cleanup._root, age=50)
    cleanup._state = lambda _: ExtractionState(video_id=1, status="failed")
    result = cleanup.cleanup()
    assert result.generations == 1
    assert newest.exists() and not older.exists()


@pytest.mark.parametrize(
    "unsafe", ["video-link", "generation-link", "frame-link", "source", "nested", "traversal"]
)
def test_cleanup_never_follows_symlinks_or_deletes_source(
    cleanup: StorageCleanupService, tmp_path: Path, unsafe: str
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"retained source")
    directory = generation(cleanup._root)
    if unsafe == "video-link":
        (cleanup._root / "2").symlink_to(tmp_path, target_is_directory=True)
    elif unsafe == "generation-link":
        (directory.parent / ("c" * 32)).symlink_to(tmp_path, target_is_directory=True)
    elif unsafe == "frame-link":
        (directory / "frame_000000000.png").symlink_to(source)
    elif unsafe == "source":
        (directory / "original.mp4").write_bytes(source.read_bytes())
    elif unsafe == "nested":
        (directory / "unexpected").mkdir()
    else:
        (cleanup._root / "..malicious").mkdir()
        (cleanup._root / "..malicious" / "source.mp4").write_bytes(source.read_bytes())
    cleanup.cleanup(now=time.time() + 200 * 3600)
    assert source.read_bytes() == b"retained source"
    if unsafe in {"frame-link", "source", "nested"}:
        assert directory.exists()


def test_cleanup_root_symlink_is_rejected(cleanup: StorageCleanupService, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    directory = generation(outside)
    cleanup._root.rmdir()
    cleanup._root.symlink_to(outside, target_is_directory=True)
    assert cleanup.cleanup().errors == 1
    assert directory.exists()


def test_cleanup_serializes_with_processing_and_other_cleanup(
    cleanup: StorageCleanupService,
) -> None:
    directory = generation(cleanup._root)
    entered = threading.Event()
    done = threading.Event()

    def clean() -> None:
        entered.set()
        cleanup.cleanup()
        done.set()

    with cleanup._lock:
        worker = threading.Thread(target=clean)
        worker.start()
        assert entered.wait(1)
        assert not done.wait(0.1)
        cleanup._active = lambda _: True
    worker.join(timeout=2)
    assert done.is_set() and directory.exists()
    cleanup._active = lambda _: False
    workers = [threading.Thread(target=cleanup.cleanup) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert not directory.exists()


def probe_script(tmp_path: Path) -> tuple[Path, Path]:
    executable = tmp_path / "slow-probe"
    pidfile = tmp_path / "probe.pid"
    executable.write_text(
        f"#!{sys.executable}\nimport os, time\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n"
    )
    executable.chmod(0o700)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    return executable, source


@pytest.mark.parametrize("reason", ["cancel", "shutdown", "timeout"])
def test_probe_stop_reasons_reap_process(tmp_path: Path, reason: str) -> None:
    executable, source = probe_script(tmp_path)
    cancel, shutdown = threading.Event(), threading.Event()
    expected = {
        "cancel": DownloadCancelledError,
        "shutdown": DownloadInterruptedError,
        "timeout": MediaValidationError,
    }[reason]
    event = shutdown if reason == "shutdown" else cancel
    stopped_at: list[float] = []
    done = threading.Event()

    def stop_when_running() -> None:
        deadline = time.monotonic() + 5
        while not (tmp_path / "probe.pid").exists() and time.monotonic() < deadline:
            if done.wait(0.01):
                return
        stopped_at.append(time.monotonic())
        event.set()

    watcher = threading.Thread(target=stop_when_running)
    if reason != "timeout":
        watcher.start()
    try:
        begun = time.monotonic()
        with pytest.raises(expected):
            FFprobeValidator(
                str(executable), timeout_seconds=1 if reason == "timeout" else 10
            ).validate(source, max_resolution=720, cancel_event=cancel, shutdown_event=shutdown)
        if reason == "timeout":
            assert time.monotonic() - begun < 2
        else:
            assert time.monotonic() - stopped_at[0] < 1
        pid = int((tmp_path / "probe.pid").read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        done.set()
        if watcher.is_alive():
            watcher.join()


def test_force_termination_reaps_uncooperative_process() -> None:
    with subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "print('ready',flush=True); time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        assert process.stdout is not None and process.stdout.readline().strip() == "ready"
        terminate_process(process, grace_seconds=0.1)
        assert process.returncode == -signal.SIGKILL


def test_process_children_are_terminated(tmp_path: Path) -> None:
    marker = tmp_path / "orphan-wrote"
    child = f"import time; time.sleep(0.8); open({str(marker)!r}, 'w').write('orphan')"
    parent = (
        f"import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "time.sleep(60)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        capture_process([sys.executable, "-c", parent], timeout=0.3, check_stop=lambda: None)
    time.sleep(0.7)
    assert not marker.exists()


def test_acquisition_error_does_not_expose_signed_url() -> None:
    message = "HTTP Error 403 https://media.invalid/?token=secret"
    error = YtDlpVideoDownloader._classify_ytdlp_error(message)
    assert "secret" not in str(error)
    assert "JavaScript" in str(error)


def test_downloader_runtime_path_configuration() -> None:
    adapter = YtDlpVideoDownloader("node", "/configured/node")
    assert adapter._runtime == "node"
    assert adapter._runtime_path == "/configured/node"
    # Actual options passed to yt-dlp are asserted in test_downloader.


def test_extraction_probe_cancellation_is_mapped(tmp_path: Path) -> None:
    from app.domain.extraction import ExtractionCancelled
    from app.infrastructure.frame_extractor import FFmpegFrameExtractor

    with (
        patch.object(FFprobeValidator, "validate", side_effect=DownloadCancelledError("stop")),
        pytest.raises(ExtractionCancelled, match="validation"),
    ):
        FFmpegFrameExtractor().extract(tmp_path / "source", tmp_path / "frames", video_id="1")


def test_cleanup_rejects_symlink_in_root_ancestors(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    directory = generation(outside / "frames")
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    service = StorageCleanupService(
        alias / "frames",
        state=lambda v: ExtractionState(video_id=v),
        active=lambda _: False,
        media_lock=threading.RLock(),
    )
    assert service.cleanup().errors == 1
    assert directory.exists()


def test_cleanup_runs_at_startup(migrated_client: object) -> None:
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    assert isinstance(migrated_client, TestClient)
    settings: Settings = migrated_client.app.state.settings  # type: ignore[attr-defined]
    assert settings.frame_dir is not None
    directory = generation(settings.frame_dir, video=987654)
    with TestClient(create_app(settings)):
        assert not directory.exists()
