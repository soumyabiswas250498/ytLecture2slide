"""Offline extraction, persistence and recovery regression coverage."""

import json
import os
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.downloads import DownloadError, DownloadStatus
from app.domain.extraction import ExtractionCancelled, ExtractionError
from app.domain.videos import LivestreamStatus
from app.infrastructure.frame_extractor import FFmpegFrameExtractor, read_manifest
from app.main import create_app
from app.repositories.extractions import ExtractionRepository
from app.repositories.videos import VideoRepository


def generate(
    path: Path, *, duration: float = 2.5, codec: str = "libx264", vfr: bool = False
) -> None:
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=320x180:rate=10:duration={duration}",
    ]
    if vfr:
        command += ["-vf", "select='if(lt(t,1),1,not(mod(n,3)))'", "-fps_mode", "vfr"]
    if codec == "libsvtav1":
        command += ["-preset", "12", "-svtav1-params", "lp=1"]
    command += ["-c:v", codec, "-threads", "1", str(path)]
    subprocess.run(command, check=True, capture_output=True)


@pytest.fixture(autouse=True, params=["seek", "sequential"])
def strategy(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    original = FFmpegFrameExtractor.__init__

    def initialize(
        self: FFmpegFrameExtractor, *, min_free_disk_mb: int = 500, threads: int = 1
    ) -> None:
        original(self, min_free_disk_mb=min_free_disk_mb, threads=threads, strategy=request.param)

    # App composition also supplies strategy; direct module tests exercise both paths separately.
    if "migrated_client" not in request.fixturenames:
        monkeypatch.setattr(FFmpegFrameExtractor, "__init__", initialize)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "source.mp4"
    generate(path)
    return path


@pytest.mark.parametrize(
    ("interval", "expected"), [(1, [0, 1, 2]), (60, [0]), (0.6, [0, 0.6, 1.2, 1.8, 2.4])]
)
def test_intervals_and_partial_tail(
    source: Path, tmp_path: Path, interval: float, expected: list[float]
) -> None:
    output = tmp_path / "frames"
    result = FFmpegFrameExtractor(min_free_disk_mb=0).extract(
        source, output, video_id="test", interval=interval
    )
    assert [f.requested_timestamp for f in result.frames] == pytest.approx(expected)
    assert [f.actual_timestamp for f in result.frames] == pytest.approx(expected)
    assert all((f.width, f.height) == (320, 180) for f in result.frames)
    assert source.is_file()
    assert read_manifest(output) == result
    assert not list(output.glob("sample_*.png"))
    assert not (output / "manifest.json.tmp").exists()
    with pytest.raises(ExtractionError, match="empty"):
        FFmpegFrameExtractor().extract(source, output, video_id="test")
    assert read_manifest(output) == result


def test_explicit_timestamps_and_range(source: Path, tmp_path: Path) -> None:
    result = FFmpegFrameExtractor(min_free_disk_mb=0).extract(
        source, tmp_path / "frames", video_id="test", timestamps=[1.25, 0.05, 0.05]
    )
    assert [f.requested_timestamp for f in result.frames] == [0.05, 1.25]
    assert [f.actual_timestamp for f in result.frames] == pytest.approx([0.1, 1.3])
    assert result.frames[0].filename == "frame_000000050.png"
    ranged = FFmpegFrameExtractor(min_free_disk_mb=0).extract(
        source, tmp_path / "range", video_id="test", start=0.5, end=2, interval=0.7
    )
    assert [f.requested_timestamp for f in ranged.frames] == pytest.approx([0.5, 1.2, 1.9])


@pytest.mark.parametrize("codec", ["libvpx-vp9", "libsvtav1"])
def test_codecs_and_vfr(tmp_path: Path, codec: str) -> None:
    source = tmp_path / "vfr.mkv"
    generate(source, codec=codec, vfr=True)
    result = FFmpegFrameExtractor(min_free_disk_mb=0).extract(
        source, tmp_path / "frames", video_id="vfr", timestamps=[0, 0.95, 1.05, 1.1, 1.95]
    )
    assert [f.actual_timestamp for f in result.frames] == pytest.approx([0, 1.2, 1.2, 1.2, 2.1])
    assert result.frame_count == 5


@pytest.mark.parametrize("timestamps", [[0.0001, 0.0002], [-1], [3], [float("nan")], []])
def test_invalid_timestamps(source: Path, tmp_path: Path, timestamps: list[float]) -> None:
    with pytest.raises(ExtractionError):
        FFmpegFrameExtractor().extract(
            source, tmp_path / "frames", video_id="test", timestamps=timestamps
        )


def test_missing_corrupt_and_disk(source: Path, tmp_path: Path) -> None:
    extractor = FFmpegFrameExtractor(min_free_disk_mb=500)
    for path in [tmp_path / "missing.mp4", tmp_path / "bad.mp4"]:
        if path.name == "bad.mp4":
            path.write_bytes(b"corrupt")
        with pytest.raises(DownloadError):
            extractor.extract(path, tmp_path / "frames", video_id="test")
    with (
        patch(
            "app.infrastructure.frame_extractor.shutil.disk_usage", return_value=MagicMock(free=0)
        ),
        pytest.raises(ExtractionError, match="disk"),
    ):
        extractor.extract(source, tmp_path / "frames", video_id="test")


def test_mid_run_disk_and_cancellation(source: Path, tmp_path: Path) -> None:
    cancel = threading.Event()

    def progress(count: int, expected: int) -> None:
        cancel.set()

    with pytest.raises(ExtractionCancelled):
        FFmpegFrameExtractor(min_free_disk_mb=0).extract(
            source,
            tmp_path / "cancel",
            video_id="test",
            interval=0.1,
            on_progress=progress,
            cancel=cancel,
        )
    assert not (tmp_path / "cancel" / "manifest.json").exists()
    with (
        patch(
            "app.infrastructure.frame_extractor.shutil.disk_usage",
            side_effect=[MagicMock(free=10**10), MagicMock(free=0)],
        ),
        pytest.raises(ExtractionError, match="disk"),
    ):
        FFmpegFrameExtractor().extract(source, tmp_path / "disk", video_id="test")


def test_manifest_integrity(source: Path, tmp_path: Path) -> None:
    output = tmp_path / "frames"
    result = FFmpegFrameExtractor(min_free_disk_mb=0).extract(source, output, video_id="test")
    target = output / result.frames[0].filename
    original = target.read_bytes()
    target.write_bytes(original[:-10])
    with pytest.raises(ExtractionError):
        read_manifest(output)
    target.write_bytes(original)
    data = json.loads((output / "manifest.json").read_text())
    data["frame_count"] = 99
    (output / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(ExtractionError, match="count"):
        read_manifest(output)


def seed(client: TestClient, source: Path) -> int:
    repo = VideoRepository(client.app.state.sessions)  # type: ignore[attr-defined]
    video, _ = repo.create_or_skip(
        channel_id=None,
        youtube_video_id="fixture001",
        title="Extraction fixture",
        description="",
        video_url="https://www.youtube.com/watch?v=fixture001",
        thumbnail_url=None,
        duration_seconds=3,
        published_at=datetime.now(UTC),
        livestream_status=LivestreamStatus.NONE,
        discovered_at=datetime.now(UTC),
    )
    repo.update_download_state(
        video.id, download_status=DownloadStatus.DOWNLOADED, local_video_path=str(source)
    )
    return video.id


def wait(client: TestClient, video_id: int, status: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/videos/{video_id}/extraction")
        data: dict[str, object] = response.json()
        if data["status"] == status:
            return data
        time.sleep(0.02)
    raise AssertionError(f"Expected {status}, got {data}")


def test_api_extraction_preview_and_deletion(migrated_client: TestClient) -> None:
    client = migrated_client
    settings: Settings = client.app.state.settings  # type: ignore[attr-defined]
    assert settings.download_dir is not None
    source = settings.download_dir / "fixture.mp4"
    generate(source)
    video_id = seed(client, source)
    assert settings.frame_dir is not None
    abandoned = settings.frame_dir / "987654" / ("f" * 32)
    abandoned.mkdir(parents=True)
    (abandoned / "sample_000000001.png").write_bytes(b"expired")
    old = time.time() - 49 * 3600
    os.utime(abandoned / "sample_000000001.png", (old, old))
    os.utime(abandoned, (old, old))
    url = f"/api/v1/videos/{video_id}"
    assert client.post(f"{url}/extraction", json={"interval_seconds": 1}).status_code == 202
    state = wait(client, video_id, "extracted")
    assert state["frame_count"] == state["expected_count"] == 3
    deadline = time.monotonic() + 2
    while abandoned.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not abandoned.exists()
    assert client.post(f"{url}/extraction", json={}).status_code == 409
    page = client.get(f"{url}/frames?page_size=2").json()
    assert len(page["items"]) == 2 and page["total"] == 3
    filename = page["items"][0]["filename"]
    assert client.get(f"{url}/frames/{filename}").content.startswith(b"\x89PNG")
    assert client.get(f"{url}/frames/secret.png").status_code == 404
    assert client.delete(f"{url}/extraction").status_code == 200
    assert source.exists()
    assert client.get(f"{url}/extraction").json()["manifest_path"] is None
    assert client.post(
        "/api/v1/videos/extractions/bulk", json={"video_ids": [video_id, video_id, 9999]}
    ).json()["started_ids"] == [video_id]
    wait(client, video_id, "extracted")


def test_cancel_conflicts_retry_and_recovery(migrated_client: TestClient) -> None:
    client = migrated_client
    settings: Settings = client.app.state.settings  # type: ignore[attr-defined]
    assert settings.download_dir is not None
    source = settings.download_dir / "fixture.mp4"
    generate(source)
    video_id = seed(client, source)
    service = client.app.state.extraction_service  # type: ignore[attr-defined]
    started = threading.Event()
    original = service._extractor

    class SlowExtractor:
        def extract(self, *args: object, **kwargs: object) -> None:
            started.set()
            signal = kwargs["cancel"]
            while not signal.is_set():  # type: ignore[attr-defined]
                time.sleep(0.01)
            raise ExtractionCancelled("interrupted")

    service._extractor = SlowExtractor()
    url = f"/api/v1/videos/{video_id}"
    assert client.post(f"{url}/extraction", json={}).status_code == 202
    assert started.wait(3)
    for operation, path in [
        (client.post, "extraction"),
        (client.delete, "extraction"),
        (client.delete, "download"),
        (client.post, "download"),
    ]:
        response = (
            client.post(f"{url}/{path}", json={})
            if operation == client.post
            else client.delete(f"{url}/{path}")
        )
        assert response.status_code == 409
    assert client.post(f"{url}/extraction/cancel").json()["status"] == "cancelled"
    service.shutdown()
    repository = ExtractionRepository(client.app.state.sessions)  # type: ignore[attr-defined]
    assert not repository.recoverable()
    # Explicit retry in a fresh application, then graceful interruption and automatic recovery.
    with TestClient(create_app(settings)) as second:
        second.app.state.extraction_service._extractor = SlowExtractor()  # type: ignore[attr-defined]
        started.clear()
        assert second.post(f"{url}/extraction/retry").status_code == 202
        assert started.wait(3)
    assert repository.get(video_id).requested
    with TestClient(create_app(settings)) as third:
        assert wait(third, video_id, "extracted")["retry_count"] == 1
    assert source.exists()
    service._extractor = original


def test_reject_missing_source_and_unsafe_delete(
    migrated_client: TestClient, tmp_path: Path
) -> None:
    client = migrated_client
    video_id = seed(client, tmp_path / "missing.mp4")
    url = f"/api/v1/videos/{video_id}"
    assert client.post(f"{url}/extraction", json={}).status_code == 422
    assert client.post(f"{url}/extraction", json={"interval_seconds": 0}).status_code == 422
    assert client.post("/api/v1/videos/99999/extraction", json={}).status_code == 404
    settings: Settings = client.app.state.settings  # type: ignore[attr-defined]
    assert settings.frame_dir is not None
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("preserve")
    (settings.frame_dir / str(video_id)).symlink_to(outside, target_is_directory=True)
    assert client.delete(f"{url}/extraction").status_code == 422
    assert (outside / "keep.txt").read_text() == "preserve"


def test_completed_manifest_reconciles_without_decoding(migrated_client: TestClient) -> None:
    client = migrated_client
    settings: Settings = client.app.state.settings  # type: ignore[attr-defined]
    assert settings.download_dir is not None and settings.frame_dir is not None
    source = settings.download_dir / "fixture.mp4"
    generate(source)
    video_id = seed(client, source)
    directory = settings.frame_dir / str(video_id) / "completed-before-crash"
    result = FFmpegFrameExtractor(min_free_disk_mb=0).extract(
        source, directory, video_id=str(video_id)
    )
    repository = ExtractionRepository(client.app.state.sessions)  # type: ignore[attr-defined]
    repository.save(video_id, requested=True, status="extracting", interval_seconds=60)
    with patch.object(
        client.app.state.extraction_service._extractor,  # type: ignore[attr-defined]
        "extract",
        side_effect=AssertionError("Must reconcile existing output"),
    ):
        client.app.state.extraction_service.recover()  # type: ignore[attr-defined]
        state = wait(client, video_id, "extracted")
    assert state["frame_directory"] == str(directory)
    assert read_manifest(directory) == result


def test_retry_limit_and_cancelled_recovery(migrated_client: TestClient) -> None:
    client = migrated_client
    settings: Settings = client.app.state.settings  # type: ignore[attr-defined]
    assert settings.download_dir is not None
    source = settings.download_dir / "fixture.mp4"
    generate(source)
    video_id = seed(client, source)
    repository = ExtractionRepository(client.app.state.sessions)  # type: ignore[attr-defined]
    repository.save(
        video_id,
        requested=True,
        status="extracting",
        retry_count=settings.extraction_retry_attempts,
    )
    client.app.state.extraction_service.recover()  # type: ignore[attr-defined]
    assert repository.get(video_id).status == "failed"
    assert not repository.get(video_id).requested
    repository.save(video_id, requested=False, status="cancelled")
    client.app.state.extraction_service.recover()  # type: ignore[attr-defined]
    assert repository.get(video_id).status == "cancelled"


def test_corrupted_download_fails_without_losing_source(migrated_client: TestClient) -> None:
    settings: Settings = migrated_client.app.state.settings  # type: ignore[attr-defined]
    assert settings.download_dir is not None
    source = settings.download_dir / "corrupt.mp4"
    source.write_bytes(b"invalid media")
    video_id = seed(migrated_client, source)
    assert migrated_client.post(f"/api/v1/videos/{video_id}/extraction", json={}).status_code == 202
    assert wait(migrated_client, video_id, "failed")["error"] is not None
    assert source.read_bytes() == b"invalid media"


def test_fractional_pts_are_not_rounded_log_timestamps(tmp_path: Path) -> None:
    source = tmp_path / "fractional.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=1",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    result = FFmpegFrameExtractor(min_free_disk_mb=0).extract(
        source, tmp_path / "frames", video_id="fractional", timestamps=[0.12345]
    )
    assert result.frames[0].actual_timestamp == pytest.approx(4 / 30, abs=1e-12)


def test_transient_resource_error_retries(migrated_client: TestClient) -> None:
    import errno

    settings: Settings = migrated_client.app.state.settings  # type: ignore[attr-defined]
    assert settings.download_dir is not None
    source = settings.download_dir / "fixture.mp4"
    generate(source)
    video_id = seed(migrated_client, source)
    extractor = migrated_client.app.state.extraction_service._extractor  # type: ignore[attr-defined]
    original = extractor.extract
    calls = 0

    def flaky(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(errno.EAGAIN, "Temporary resource exhaustion")
        return original(*args, **kwargs)

    with patch.object(extractor, "extract", side_effect=flaky):
        assert (
            migrated_client.post(f"/api/v1/videos/{video_id}/extraction", json={}).status_code
            == 202
        )
        assert wait(migrated_client, video_id, "extracted")["retry_count"] == 1
    assert calls == 2


def test_end_boundary_and_sampling_limit(source: Path, tmp_path: Path) -> None:
    with pytest.raises(ExtractionError):
        FFmpegFrameExtractor(min_free_disk_mb=0).extract(
            source, tmp_path / "boundary", video_id="test", timestamps=[1.25], end=1.27
        )
    extractor = FFmpegFrameExtractor(min_free_disk_mb=0)
    extractor._max_frames = 10
    with pytest.raises(ExtractionError, match="limit"):
        extractor.extract(source, tmp_path / "huge", video_id="test", interval=0.001)


@pytest.mark.parametrize("invalidation", ["source", "interval", "corrupt", "incomplete"])
def test_recovery_rejects_mismatched_or_incomplete_generations(
    migrated_client: TestClient, invalidation: str
) -> None:
    client = migrated_client
    settings: Settings = client.app.state.settings  # type: ignore[attr-defined]
    assert settings.download_dir is not None and settings.frame_dir is not None
    source = settings.download_dir / "recovery.mp4"
    generate(source)
    video_id = seed(client, source)
    directory = settings.frame_dir / str(video_id) / ("a" * 32)
    result = FFmpegFrameExtractor(min_free_disk_mb=0).extract(
        source, directory, video_id=str(video_id)
    )
    if invalidation == "source":
        source.write_bytes(source.read_bytes() + b"changed")
    elif invalidation == "interval":
        data = result.model_dump(mode="json")
        data["interval_seconds"] = 30
        (directory / "manifest.json").write_text(json.dumps(data))
    elif invalidation == "corrupt":
        (directory / result.frames[0].filename).write_bytes(b"corrupt")
    else:
        (directory / "manifest.json").unlink()
    service = client.app.state.extraction_service  # type: ignore[attr-defined]
    assert service._reusable_result(source, video_id, 60) is None
    assert directory.exists() and source.exists()
