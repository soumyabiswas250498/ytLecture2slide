"""Automated tests for Phase 4 — Video Acquisition."""

import subprocess
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.downloads import (
    DownloadCancelledError,
    DownloadError,
    DownloadInterruptedError,
    DownloadProgress,
    DownloadRequest,
    DownloadStatus,
    MediaProbeResult,
    MediaValidationError,
    ProgressCallback,
    UnsupportedFormatError,
)
from app.domain.videos import LivestreamStatus
from app.infrastructure.database import create_database_engine, session_factory
from app.infrastructure.media_probe import FFprobeValidator
from app.infrastructure.ytdlp_downloader import (
    YtDlpVideoDownloader,
    resolve_safe_destination,
    sanitize_youtube_video_id,
)
from app.main import create_app
from app.repositories.videos import VideoRepository


def _alembic_upgrade(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "head")


@pytest.fixture()
def app_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[TestClient, Settings, VideoRepository]]:
    storage = tmp_path / "storage"
    db_path = storage / "database" / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _alembic_upgrade(monkeypatch, db_path)

    settings = Settings(
        app_env="test",
        storage_dir=storage,
        temp_dir=storage / "jobs",
        database_path=db_path,
        download_dir=storage / "jobs" / "videos",
        download_max_resolution=720,
        download_audio_enabled=False,
        download_concurrent_limit=1,
        download_retry_attempts=2,
        download_connect_timeout_seconds=10,
        download_inactivity_timeout_seconds=30,
        download_max_total_timeout_seconds=None,
        download_min_free_disk_mb=50,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        repo = VideoRepository(app.state.sessions)
        yield client, settings, repo


def _seed_video(
    repo: VideoRepository,
    youtube_video_id: str = "dQw4w9WgXcQ",
    title: str = "Sample Lecture",
) -> int:
    entity, _ = repo.create_or_skip(
        channel_id=None,
        youtube_video_id=youtube_video_id,
        title=title,
        description="",
        video_url=f"https://www.youtube.com/watch?v={youtube_video_id}",
        thumbnail_url=None,
        duration_seconds=1800,
        published_at=datetime(2026, 11, 20, 10, 0, tzinfo=UTC),
        livestream_status=LivestreamStatus.NONE,
        discovered_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
    )
    return entity.id


def _wait_for_status(
    repo: VideoRepository,
    video_id: int,
    expected: set[DownloadStatus],
    timeout: float = 5.0,
) -> DownloadStatus:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entity = repo.get_by_id(video_id)
        if entity is not None and entity.download_status in expected:
            return entity.download_status
        time.sleep(0.05)
    entity = repo.get_by_id(video_id)
    raise AssertionError(
        f"Timed out waiting for status {expected}; got {entity.download_status if entity else None}"
    )


# ------------------------------------------------------------------
# Unit tests: path safety & yt-dlp adapter configuration
# ------------------------------------------------------------------


def test_sanitize_youtube_video_id_rejects_traversal() -> None:
    assert sanitize_youtube_video_id("abc_123-XYZ") == "abc_123-XYZ"
    for bad in ("../etc/passwd", "abc/def", "a b c", "", "x"):
        with pytest.raises(DownloadError):
            sanitize_youtube_video_id(bad)


def test_resolve_safe_destination_blocks_escape(tmp_path: Path) -> None:
    dest = tmp_path / "videos"
    dest.mkdir()
    safe = resolve_safe_destination(dest, "abc123.mp4")
    assert safe == (dest / "abc123.mp4").resolve()
    with pytest.raises(DownloadError):
        resolve_safe_destination(dest, "../secret.mp4")


def test_ytdlp_format_selector_is_video_only_and_capped() -> None:
    selector = YtDlpVideoDownloader._build_format_selector(max_resolution=720, audio_enabled=False)
    assert "height<=720" in selector
    assert "acodec=none" in selector
    assert "+bestaudio" not in selector


def test_ytdlp_adapter_passes_strict_options(tmp_path: Path) -> None:
    captured_opts: dict[str, object] = {}
    out_file = tmp_path / "abc1234.mp4"
    out_file.write_bytes(b"fake-video-bytes")

    class FakeYDL:
        def __init__(self, opts: dict[str, object]) -> None:
            captured_opts.update(opts)

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, download: bool = True) -> dict[str, object]:
            return {"requested_downloads": [{"filepath": str(out_file)}]}

        def prepare_filename(self, info: dict[str, object]) -> str:
            return str(out_file)

    with patch("app.infrastructure.ytdlp_downloader.YoutubeDL", FakeYDL):
        adapter = YtDlpVideoDownloader()
        result = adapter.download(
            DownloadRequest(
                video_id=1,
                youtube_video_id="abc1234",
                video_url="https://www.youtube.com/watch?v=abc1234",
                destination_dir=tmp_path,
                max_resolution=720,
                audio_enabled=False,
            )
        )

    assert result == out_file.resolve()
    assert captured_opts["js_runtimes"] == {"deno": {"path": None}}
    assert captured_opts["remote_components"] == set()
    assert captured_opts["noplaylist"] is True
    assert captured_opts["writesubtitles"] is False
    assert captured_opts["writeautomaticsub"] is False
    assert captured_opts["writethumbnail"] is False
    assert captured_opts["writeinfojson"] is False
    assert captured_opts["continuedl"] is True


# ------------------------------------------------------------------
# Real FFprobe validation tests using synthetic ffmpeg fixtures
# ------------------------------------------------------------------


def _generate_synthetic_mp4(path: Path, *, size: str, with_audio: bool) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=blue:s={size}:d=1",
    ]
    if with_audio:
        cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-shortest"])
    cmd.extend(["-c:v", "libx264", "-t", "1", str(path)])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        pytest.skip(f"ffmpeg unavailable or failed to generate fixture: {proc.stderr}")


def test_ffprobe_validator_accepts_video_only_720p_or_lower(tmp_path: Path) -> None:
    video_path = tmp_path / "valid_480p.mp4"
    _generate_synthetic_mp4(video_path, size="854x480", with_audio=False)

    validator = FFprobeValidator()
    probe = validator.validate(video_path, max_resolution=720, require_no_audio=True)
    assert probe.width == 854
    assert probe.height == 480
    assert probe.resolution_label == "854x480"
    assert probe.has_audio is False
    assert probe.video_codec == "h264"
    assert probe.duration_seconds > 0
    assert probe.file_size_bytes > 0


def test_ffprobe_validator_rejects_audio_stream(tmp_path: Path) -> None:
    video_path = tmp_path / "with_audio.mp4"
    _generate_synthetic_mp4(video_path, size="640x360", with_audio=True)

    validator = FFprobeValidator()
    with pytest.raises(MediaValidationError, match="audio"):
        validator.validate(video_path, max_resolution=720, require_no_audio=True)


def test_ffprobe_validator_rejects_exceeding_max_resolution(tmp_path: Path) -> None:
    video_path = tmp_path / "too_high_1080p.mp4"
    _generate_synthetic_mp4(video_path, size="1920x1080", with_audio=False)

    validator = FFprobeValidator()
    with pytest.raises(MediaValidationError, match="exceeds maximum"):
        validator.validate(video_path, max_resolution=720, require_no_audio=True)


def test_ffprobe_validator_rejects_corrupt_or_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    validator = FFprobeValidator()
    with pytest.raises(MediaValidationError, match="empty"):
        validator.validate(empty, max_resolution=720)

    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not-a-valid-mp4-header")
    with pytest.raises(MediaValidationError):
        validator.validate(corrupt, max_resolution=720)


# ------------------------------------------------------------------
# Integration tests: API, concurrency, progress, cancel, retry, delete
# ------------------------------------------------------------------


def test_download_success_persists_metadata_and_prevents_duplicates(
    app_env: tuple[TestClient, Settings, VideoRepository],
) -> None:
    client, settings, repo = app_env
    vid_id = _seed_video(repo, "vidSuccess1")
    assert settings.download_dir is not None

    class SuccessDownloader:
        def download(
            self,
            request: DownloadRequest,
            *,
            on_progress: ProgressCallback | None = None,
            cancel_event: Event | None = None,
            shutdown_event: Event | None = None,
        ) -> Path:
            out = request.destination_dir / f"{request.youtube_video_id}.mp4"
            out.write_bytes(b"valid-bytes")
            if on_progress:
                on_progress(
                    DownloadProgress(
                        video_id=request.video_id,
                        youtube_video_id=request.youtube_video_id,
                        status=DownloadStatus.DOWNLOADING,
                        progress_percent=50.0,
                        downloaded_bytes=512,
                        total_bytes=1024,
                        speed_bytes_per_sec=1024.0,
                        eta_seconds=1.0,
                    )
                )
            return out

    fake_validator = MagicMock()
    fake_validator.validate.return_value = MediaProbeResult(
        width=1280,
        height=720,
        resolution_label="1280x720",
        duration_seconds=1800.0,
        video_codec="h264",
        has_audio=False,
        file_size_bytes=1024,
    )

    service = client.app.state.download_service  # type: ignore[attr-defined]
    service._downloader = SuccessDownloader()
    service._validator = fake_validator

    resp = client.post(f"/api/v1/videos/{vid_id}/download")
    assert resp.status_code == 202
    assert resp.json()["download_status"] == "downloading"

    final_status = _wait_for_status(repo, vid_id, {DownloadStatus.DOWNLOADED})
    assert final_status == DownloadStatus.DOWNLOADED

    entity = repo.get_by_id(vid_id)
    assert entity is not None
    assert entity.actual_resolution == "1280x720"
    assert entity.video_codec == "h264"
    assert entity.file_size_bytes == 1024
    assert entity.download_progress == 100.0
    assert entity.local_video_path is not None

    # Duplicate download must be rejected with 409.
    dup = client.post(f"/api/v1/videos/{vid_id}/download")
    assert dup.status_code == 409

    # Repeat discovery must NOT reset download metadata.
    existing, created = repo.create_or_skip(
        channel_id=None,
        youtube_video_id="vidSuccess1",
        title="Sample Lecture",
        description="",
        video_url="https://www.youtube.com/watch?v=vidSuccess1",
        thumbnail_url=None,
        duration_seconds=1800,
        published_at=datetime(2026, 11, 20, 10, 0, tzinfo=UTC),
        livestream_status=LivestreamStatus.NONE,
        discovered_at=datetime(2026, 11, 21, 12, 0, tzinfo=UTC),
    )
    assert created is False
    assert existing.download_status == DownloadStatus.DOWNLOADED
    assert existing.actual_resolution == "1280x720"


def test_concurrent_download_and_cancellation(
    app_env: tuple[TestClient, Settings, VideoRepository],
) -> None:
    client, _, repo = app_env
    vid_id = _seed_video(repo, "vidCancel1")
    started = Event()

    class SlowDownloader:
        def download(
            self,
            request: DownloadRequest,
            *,
            on_progress: ProgressCallback | None = None,
            cancel_event: Event | None = None,
            shutdown_event: Event | None = None,
        ) -> Path:
            part = request.destination_dir / f"{request.youtube_video_id}.mp4.part"
            part.write_bytes(b"partial")
            if on_progress:
                on_progress(
                    DownloadProgress(
                        video_id=request.video_id,
                        youtube_video_id=request.youtube_video_id,
                        status=DownloadStatus.DOWNLOADING,
                        progress_percent=42.5,
                        downloaded_bytes=425,
                        total_bytes=1000,
                        speed_bytes_per_sec=250.0,
                        eta_seconds=2.0,
                    )
                )
            started.set()
            assert cancel_event is not None
            cancel_event.wait(timeout=5.0)
            raise DownloadCancelledError("Download cancelled by user.")

    service = client.app.state.download_service  # type: ignore[attr-defined]
    service._downloader = SlowDownloader()

    resp = client.post(f"/api/v1/videos/{vid_id}/download")
    assert resp.status_code == 202
    assert started.wait(timeout=3.0)

    # Concurrent request for same video must be rejected with 409.
    conflict = client.post(f"/api/v1/videos/{vid_id}/download")
    assert conflict.status_code == 409

    # Live progress endpoint returns active progress.
    prog = client.get(f"/api/v1/videos/{vid_id}/download/progress")
    assert prog.status_code == 200
    assert prog.json()["progress_percent"] == 42.5
    assert prog.json()["speed_bytes_per_sec"] == 250.0

    # Cancel active download.
    cancel_resp = client.post(f"/api/v1/videos/{vid_id}/download/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["download_status"] == "cancelled"

    final = _wait_for_status(repo, vid_id, {DownloadStatus.CANCELLED})
    assert final == DownloadStatus.CANCELLED


def test_transient_retry_recovers_and_permanent_failure_marks_failed(
    app_env: tuple[TestClient, Settings, VideoRepository],
) -> None:
    client, _, repo = app_env
    vid_retry = _seed_video(repo, "vidRetry1", "Retry Lecture")
    vid_fail = _seed_video(repo, "vidFail01", "Fail Lecture")

    attempts = {"count": 0}

    class FlakyDownloader:
        def download(
            self,
            request: DownloadRequest,
            *,
            on_progress: ProgressCallback | None = None,
            cancel_event: Event | None = None,
            shutdown_event: Event | None = None,
        ) -> Path:
            if request.youtube_video_id == "vidFail01":
                raise UnsupportedFormatError("No 720p stream.", recoverable=False)
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise DownloadError("Transient network reset", recoverable=True)
            out = request.destination_dir / f"{request.youtube_video_id}.mp4"
            out.write_bytes(b"ok")
            return out

    fake_validator = MagicMock()
    fake_validator.validate.return_value = MediaProbeResult(
        width=854,
        height=480,
        resolution_label="854x480",
        duration_seconds=1500.0,
        video_codec="vp9",
        has_audio=False,
        file_size_bytes=2048,
    )

    service = client.app.state.download_service  # type: ignore[attr-defined]
    service._downloader = FlakyDownloader()
    service._validator = fake_validator

    with patch("threading.Event.wait", return_value=False):
        assert client.post(f"/api/v1/videos/{vid_retry}/download").status_code == 202
        assert _wait_for_status(repo, vid_retry, {DownloadStatus.DOWNLOADED}) == (
            DownloadStatus.DOWNLOADED
        )
        assert attempts["count"] == 2

        assert client.post(f"/api/v1/videos/{vid_fail}/download").status_code == 202
        assert _wait_for_status(repo, vid_fail, {DownloadStatus.FAILED}) == DownloadStatus.FAILED

    failed_entity = repo.get_by_id(vid_fail)
    assert failed_entity is not None
    assert failed_entity.download_error is not None
    assert "No 720p stream" in failed_entity.download_error


def test_insufficient_disk_space_returns_507(
    app_env: tuple[TestClient, Settings, VideoRepository],
) -> None:
    client, _, repo = app_env
    vid_id = _seed_video(repo, "vidDisk01")

    fake_usage = MagicMock(free=1024 * 1024)  # 1 MB < 50 MB minimum
    with patch("shutil.disk_usage", return_value=fake_usage):
        resp = client.post(f"/api/v1/videos/{vid_id}/download")
    assert resp.status_code == 507


def test_invalid_ffprobe_output_cleans_file_and_marks_failed(
    app_env: tuple[TestClient, Settings, VideoRepository],
) -> None:
    client, settings, repo = app_env
    vid_id = _seed_video(repo, "vidBad001")
    assert settings.download_dir is not None

    class BadFileDownloader:
        def download(
            self,
            request: DownloadRequest,
            *,
            on_progress: ProgressCallback | None = None,
            cancel_event: Event | None = None,
            shutdown_event: Event | None = None,
        ) -> Path:
            out = request.destination_dir / f"{request.youtube_video_id}.mp4"
            out.write_bytes(b"corrupt")
            return out

    bad_validator = MagicMock()
    bad_validator.validate.side_effect = MediaValidationError("Unexpected audio stream.")

    service = client.app.state.download_service  # type: ignore[attr-defined]
    service._downloader = BadFileDownloader()
    service._validator = bad_validator

    assert client.post(f"/api/v1/videos/{vid_id}/download").status_code == 202
    assert _wait_for_status(repo, vid_id, {DownloadStatus.FAILED}) == DownloadStatus.FAILED
    assert not (settings.download_dir / "vidBad001.mp4").exists()


def test_bulk_download_and_safe_local_deletion(
    app_env: tuple[TestClient, Settings, VideoRepository],
) -> None:
    client, settings, repo = app_env
    vid1 = _seed_video(repo, "vidBulk01", "Bulk 1")
    vid2 = _seed_video(repo, "vidBulk02", "Bulk 2")
    assert settings.download_dir is not None

    class BulkOkDownloader:
        def download(
            self,
            request: DownloadRequest,
            *,
            on_progress: ProgressCallback | None = None,
            cancel_event: Event | None = None,
            shutdown_event: Event | None = None,
        ) -> Path:
            out = request.destination_dir / f"{request.youtube_video_id}.mp4"
            out.write_bytes(b"ok-video")
            return out

    fake_validator = MagicMock()
    fake_validator.validate.return_value = MediaProbeResult(
        width=1280,
        height=720,
        resolution_label="1280x720",
        duration_seconds=1800.0,
        video_codec="h264",
        has_audio=False,
        file_size_bytes=8,
    )

    service = client.app.state.download_service  # type: ignore[attr-defined]
    service._downloader = BulkOkDownloader()
    service._validator = fake_validator

    bulk_resp = client.post(
        "/api/v1/videos/downloads/bulk",
        json={"video_ids": [vid1, vid2, 999999]},
    )
    assert bulk_resp.status_code == 202
    data = bulk_resp.json()
    assert set(data["started_ids"]) == {vid1, vid2}
    assert len(data["errors"]) == 1

    assert _wait_for_status(repo, vid1, {DownloadStatus.DOWNLOADED}) == DownloadStatus.DOWNLOADED
    assert _wait_for_status(repo, vid2, {DownloadStatus.DOWNLOADED}) == DownloadStatus.DOWNLOADED

    local_file = settings.download_dir / "vidBulk01.mp4"
    assert local_file.exists()

    del_resp = client.delete(f"/api/v1/videos/{vid1}/download")
    assert del_resp.status_code == 200
    assert del_resp.json()["download_status"] == "pending"
    assert del_resp.json()["local_video_path"] is None
    assert not local_file.exists()


def test_startup_reconciles_stale_downloading_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "app.db"
    _alembic_upgrade(monkeypatch, db_path)
    engine = create_database_engine(db_path)
    try:
        sessions = session_factory(engine)
        repo = VideoRepository(sessions)
        vid_id = _seed_video(repo, "vidStale1")
        repo.update_download_state(
            vid_id, download_status=DownloadStatus.DOWNLOADING, download_requested=True
        )

        recoverable = repo.list_recoverable_downloads()
        assert [v.id for v in recoverable] == [vid_id]
    finally:
        engine.dispose()


def test_graceful_shutdown_preserves_part_files_and_auto_recovers_on_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    storage = tmp_path / "storage"
    db_path = storage / "database" / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _alembic_upgrade(monkeypatch, db_path)

    settings = Settings(
        app_env="test",
        storage_dir=storage,
        temp_dir=storage / "jobs",
        database_path=db_path,
        download_dir=storage / "jobs" / "videos",
        download_max_resolution=720,
        download_audio_enabled=False,
        download_concurrent_limit=1,
        download_retry_attempts=2,
        download_min_free_disk_mb=50,
    )

    from app.services.downloader import VideoDownloadService

    engine = create_database_engine(db_path)
    try:
        sessions = session_factory(engine)
        repo = VideoRepository(sessions)
        vid_recover = _seed_video(repo, "vidRecov1", "Recover Me")
        vid_cancel = _seed_video(repo, "vidCanc01", "Stay Cancelled")
        repo.update_download_state(
            vid_cancel,
            download_status=DownloadStatus.CANCELLED,
            download_requested=False,
            download_error="Download cancelled by user.",
        )

        started = Event()

        class InterruptibleDownloader:
            def download(
                self,
                request: DownloadRequest,
                *,
                on_progress: ProgressCallback | None = None,
                cancel_event: Event | None = None,
                shutdown_event: Event | None = None,
            ) -> Path:
                part = request.destination_dir / f"{request.youtube_video_id}.mp4.part"
                part.write_bytes(b"partial-data")
                if on_progress:
                    on_progress(
                        DownloadProgress(
                            video_id=request.video_id,
                            youtube_video_id=request.youtube_video_id,
                            status=DownloadStatus.DOWNLOADING,
                            progress_percent=35.0,
                            downloaded_bytes=350,
                            total_bytes=1000,
                            speed_bytes_per_sec=100.0,
                            eta_seconds=6.5,
                            is_live=True,
                        )
                    )
                started.set()
                assert shutdown_event is not None
                shutdown_event.wait(timeout=5.0)
                raise DownloadInterruptedError("Shutdown interrupted")

        svc1 = VideoDownloadService(
            video_repo=repo,
            downloader=InterruptibleDownloader(),
            validator=MagicMock(),
            settings=settings,
        )
        svc1.start_download(vid_recover)
        assert started.wait(timeout=3.0)

        svc1.shutdown()

        # New requests must be rejected during shutdown.
        with pytest.raises(DownloadError, match="shutting down"):
            svc1.start_download(vid_cancel)

        # Partial file and persisted state must be preserved.
        part_file = settings.download_dir / "vidRecov1.mp4.part"  # type: ignore[operator]
        assert part_file.exists()
        persisted = repo.get_by_id(vid_recover)
        assert persisted is not None
        assert persisted.download_status == DownloadStatus.DOWNLOADING
        assert persisted.download_requested is True
        assert persisted.downloaded_bytes == 350
        assert persisted.total_bytes == 1000

        # Non-live progress from DB must have is_live=False and no speed/ETA.
        db_prog = svc1.get_progress(vid_recover)
        assert db_prog.is_live is False
        assert db_prog.speed_bytes_per_sec is None
        assert db_prog.eta_seconds is None

        # Simulate restart with a resuming downloader.
        resumed_with_part = {"saw_part": False}

        class ResumingDownloader:
            def download(
                self,
                request: DownloadRequest,
                *,
                on_progress: ProgressCallback | None = None,
                cancel_event: Event | None = None,
                shutdown_event: Event | None = None,
            ) -> Path:
                part = request.destination_dir / f"{request.youtube_video_id}.mp4.part"
                resumed_with_part["saw_part"] = part.exists()
                out = request.destination_dir / f"{request.youtube_video_id}.mp4"
                out.write_bytes(b"full-resumed-video")
                if part.exists():
                    part.unlink()
                return out

        fake_validator = MagicMock()
        fake_validator.validate.return_value = MediaProbeResult(
            width=1280,
            height=720,
            resolution_label="1280x720",
            duration_seconds=1800.0,
            video_codec="h264",
            has_audio=False,
            file_size_bytes=18,
        )

        svc2 = VideoDownloadService(
            video_repo=repo,
            downloader=ResumingDownloader(),
            validator=fake_validator,
            settings=settings,
        )
        try:
            recovered = svc2.recover_interrupted_downloads()
            assert recovered == 1
            assert _wait_for_status(repo, vid_recover, {DownloadStatus.DOWNLOADED}) == (
                DownloadStatus.DOWNLOADED
            )
            assert resumed_with_part["saw_part"] is True

            # Cancelled video must NEVER be restarted on recovery.
            cancelled = repo.get_by_id(vid_cancel)
            assert cancelled is not None
            assert cancelled.download_status == DownloadStatus.CANCELLED
        finally:
            svc2.shutdown()
    finally:
        engine.dispose()


def test_inactivity_timeout_triggers_recoverable_error(tmp_path: Path) -> None:
    class StalledYDL:
        def __init__(self, opts: dict[str, object]) -> None:
            self._hooks = opts["progress_hooks"]

        def __enter__(self) -> "StalledYDL":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, download: bool = True) -> dict[str, object]:
            hook = self._hooks[0]  # type: ignore[index]
            hook({"status": "downloading", "downloaded_bytes": 100, "total_bytes": 1000})
            time.sleep(0.05)
            hook({"status": "downloading", "downloaded_bytes": 100, "total_bytes": 1000})
            return {}

    with (
        patch("app.infrastructure.ytdlp_downloader.YoutubeDL", StalledYDL),
        patch(
            "app.infrastructure.ytdlp_downloader.time.monotonic",
            side_effect=[0.0, 0.0, 15.0],
        ),
        pytest.raises(DownloadError, match="inactivity") as exc_info,
    ):
        YtDlpVideoDownloader().download(
            DownloadRequest(
                video_id=1,
                youtube_video_id="vidStall1",
                video_url="https://www.youtube.com/watch?v=vidStall1",
                destination_dir=tmp_path,
                inactivity_timeout_seconds=10,
                max_total_timeout_seconds=None,
            )
        )
    assert exc_info.value.recoverable is True


@pytest.mark.parametrize("reason", ["cancel", "shutdown"])
def test_stop_arriving_at_probe_completion_cannot_publish_success(
    app_env: tuple[TestClient, Settings, VideoRepository], reason: str
) -> None:
    client, settings, repo = app_env
    video_id = _seed_video(repo, "probeStop01")
    service = client.app.state.download_service  # type: ignore[attr-defined]
    assert settings.download_dir is not None
    path = settings.download_dir / "probeStop01.mp4"
    path.write_bytes(b"verified")
    service._downloader = MagicMock()
    service._downloader.download.return_value = path
    checked = Event()

    def validate(
        file_path: Path,
        *,
        max_resolution: int,
        require_no_audio: bool,
        cancel_event: Event,
        shutdown_event: Event,
    ) -> MediaProbeResult:
        (cancel_event if reason == "cancel" else shutdown_event).set()
        checked.set()
        return MediaProbeResult(
            width=1280,
            height=720,
            resolution_label="1280x720",
            duration_seconds=1800,
            video_codec="av1",
            has_audio=False,
            file_size_bytes=8,
        )

    service._validator = MagicMock()
    service._validator.validate.side_effect = validate
    assert client.post(f"/api/v1/videos/{video_id}/download").status_code == 202
    assert checked.wait(2)
    deadline = time.monotonic() + 2
    while video_id in service._active_videos and time.monotonic() < deadline:
        time.sleep(0.01)
    state = repo.get_by_id(video_id)
    assert state is not None
    assert state.download_status == (
        DownloadStatus.CANCELLED if reason == "cancel" else DownloadStatus.DOWNLOADING
    )
    assert state.download_requested is (reason == "shutdown")
    assert state.local_video_path is None
    if reason == "shutdown":
        assert path.exists()
