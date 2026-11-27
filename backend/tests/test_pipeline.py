"""Tests for Phase 8: automated pipeline orchestration, scheduling, and cleanup."""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.downloads import DownloadStatus
from app.domain.videos import LivestreamStatus, ProcessingStatus
from app.infrastructure.models import ChannelRecord, PdfGenerationRecord, VideoRecord, utc_now
from app.main import create_app
from app.repositories.pipeline import PipelineRepository
from app.services.pipeline import PipelineOrchestrator
from app.services.scheduler import DAILY_JOB_ID, PipelineSchedulerService


def _create_synthetic_video(path: Path, *, duration: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=640x360:rate=2:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _seed_video(
    client: TestClient,
    *,
    youtube_video_id: str = "vid_pipe_001",
    title: str = "Quantitative Aptitude Lecture 1",
    duration_seconds: int = 1800,
    is_excluded: bool = False,
    livestream_status: str = LivestreamStatus.NONE.value,
    local_video_path: Path | None = None,
) -> int:
    sessions = client.app.state.sessions  # type: ignore[attr-defined]
    with sessions() as session:
        channel = session.query(ChannelRecord).first()
        if channel is None:
            channel = ChannelRecord(
                name="Test Channel",
                channel_url="https://www.youtube.com/@testchannel",
                search_keyword="IDO",
                is_active=True,
            )
            session.add(channel)
            session.flush()
        video = VideoRecord(
            channel_id=channel.id,
            channel_name=channel.name,
            youtube_video_id=youtube_video_id,
            title=title,
            description="",
            video_url=f"https://www.youtube.com/watch?v={youtube_video_id}",
            duration_seconds=duration_seconds,
            published_at=utc_now() - timedelta(days=1),
            livestream_status=livestream_status,
            discovered_at=utc_now(),
            processing_status=ProcessingStatus.PENDING.value,
            download_status=(
                DownloadStatus.DOWNLOADED.value
                if local_video_path is not None
                else DownloadStatus.PENDING.value
            ),
            local_video_path=str(local_video_path) if local_video_path is not None else None,
            is_excluded=is_excluded,
        )
        session.add(video)
        session.commit()
        session.refresh(video)
        return video.id


def _wait_for_run(client: TestClient, run_id: int, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/pipeline/runs/{run_id}")
        assert resp.status_code == 200
        data: dict[str, Any] = resp.json()
        if data["status"] in {"completed", "completed_with_errors", "failed", "cancelled"}:
            return data
        time.sleep(0.1)
    raise AssertionError(f"Pipeline run #{run_id} did not finish within {timeout}s")


@pytest.fixture
def pipeline_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "database" / "app.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "head")

    settings = Settings(
        app_env="test",
        storage_dir=tmp_path,
        temp_dir=tmp_path / "jobs",
        database_path=db_path,
        extraction_interval_seconds=1.0,
        pipeline_retry_attempts=1,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def test_end_to_end_pipeline_and_cleanup(pipeline_client: TestClient, tmp_path: Path) -> None:
    client = pipeline_client
    dl_dir = tmp_path / "jobs" / "videos"
    dl_dir.mkdir(parents=True, exist_ok=True)
    src_video = dl_dir / "vid_e2e_001.mp4"
    _create_synthetic_video(src_video, duration=3)
    video_id = _seed_video(client, youtube_video_id="vid_e2e_001", local_video_path=src_video)

    # Trigger manual run for this video.
    resp = client.post("/api/v1/pipeline/runs", json={"video_ids": [video_id]})
    assert resp.status_code == 202
    run_id = resp.json()["id"]

    final = _wait_for_run(client, run_id)
    assert final["status"] == "completed"
    assert final["completed_videos"] == 1
    assert final["failed_videos"] == 0
    assert final["videos"][0]["cleaned"] is True

    # Verify PDF exists, is readable, and passes integrity checks.
    pdf_resp = client.get(f"/api/v1/videos/{video_id}/pdf")
    assert pdf_resp.status_code == 200
    pdf_data = pdf_resp.json()
    assert pdf_data["status"] == "generated"
    assert pdf_data["page_count"] >= 1
    pdf_path = Path(pdf_data["pdf_path"])
    assert pdf_path.is_file()
    with pymupdf.open(str(pdf_path)) as doc:
        assert len(doc) == pdf_data["page_count"]

    # Verify intermediate files were removed and Cleaned state is persisted.
    assert not src_video.exists()
    assert not (tmp_path / "jobs" / "frames" / str(video_id)).exists()
    assert not (tmp_path / "jobs" / "slides" / str(video_id)).exists()

    vid_resp = client.get(f"/api/v1/videos/{video_id}")
    assert vid_resp.status_code == 200
    vid_json = vid_resp.json()
    assert vid_json["download_status"] == "cleaned"
    assert vid_json["intermediates_cleaned"] is True

    # PDF download endpoint still works after cleanup.
    dl_pdf = client.get(f"/api/v1/pdfs/{video_id}/download")
    assert dl_pdf.status_code == 200
    assert dl_pdf.content.startswith(b"%PDF-")

    # Cleanup is idempotent.
    cleanup_resp = client.post(f"/api/v1/pipeline/videos/{video_id}/cleanup")
    assert cleanup_resp.status_code == 200
    assert cleanup_resp.json()["cleaned"] is True
    assert cleanup_resp.json()["deleted_files"] == 0

    # Re-running without reprocess_existing skips already-completed PDF.
    resp2 = client.post("/api/v1/pipeline/runs", json={"video_ids": [video_id]})
    assert resp2.status_code == 202
    final2 = _wait_for_run(pipeline_client, resp2.json()["id"])
    assert final2["status"] == "completed"
    assert final2["skipped_videos"] == 1
    assert final2["completed_videos"] == 0


def test_exclusion_enforcement_and_failure_isolation(
    pipeline_client: TestClient, tmp_path: Path
) -> None:
    client = pipeline_client
    dl_dir = tmp_path / "jobs" / "videos"
    dl_dir.mkdir(parents=True, exist_ok=True)
    ok_video = dl_dir / "vid_ok_001.mp4"
    _create_synthetic_video(ok_video, duration=2)

    client.put("/api/v1/settings/exclusion-keywords", json={"keywords": ["Mock"]})
    excluded_id = _seed_video(
        client,
        youtube_video_id="vid_excl_001",
        title="Mock Test Live",
        is_excluded=True,
    )
    failing_id = _seed_video(
        client,
        youtube_video_id="vid_fail_001",
        title="Broken Video",
        local_video_path=None,  # No file and no yt-dlp download URL will fail
    )
    ok_id = _seed_video(
        client,
        youtube_video_id="vid_ok_001",
        title="Valid Lecture",
        local_video_path=ok_video,
    )

    # Mock downloader to fail immediately for failing_id so test is fast & offline.
    dl_service = client.app.state.download_service  # type: ignore[attr-defined]
    orig_start = dl_service.start_download

    def fake_start(vid: int) -> object:
        if vid == failing_id:
            from app.domain.downloads import DownloadError

            raise DownloadError("Simulated permanent acquisition failure", recoverable=False)
        return orig_start(vid)

    dl_service.start_download = fake_start

    resp = client.post(
        "/api/v1/pipeline/runs",
        json={"video_ids": [excluded_id, failing_id, ok_id]},
    )
    assert resp.status_code == 202
    final = _wait_for_run(client, resp.json()["id"])
    assert final["status"] == "completed_with_errors"
    assert final["excluded_videos"] == 1
    assert final["failed_videos"] == 1
    assert final["completed_videos"] == 1


def test_failed_pdf_validation_preserves_intermediates(
    pipeline_client: TestClient, tmp_path: Path
) -> None:
    client = pipeline_client
    dl_dir = tmp_path / "jobs" / "videos"
    dl_dir.mkdir(parents=True, exist_ok=True)
    src_video = dl_dir / "vid_corrupt_pdf.mp4"
    _create_synthetic_video(src_video, duration=2)
    video_id = _seed_video(client, youtube_video_id="vid_corrupt_pdf", local_video_path=src_video)

    # Create a corrupt PDF record pointing to an invalid file.
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    bad_pdf = pdf_dir / "corrupt.pdf"
    bad_pdf.write_bytes(b"not-a-valid-pdf")

    sessions = client.app.state.sessions  # type: ignore[attr-defined]
    with sessions() as session:
        session.add(
            PdfGenerationRecord(
                video_id=video_id,
                status="generated",
                pdf_path=str(bad_pdf),
                pdf_filename="corrupt.pdf",
                page_count=1,
                file_size_bytes=bad_pdf.stat().st_size,
            )
        )
        session.commit()

    cleanup_resp = client.post(f"/api/v1/pipeline/videos/{video_id}/cleanup")
    assert cleanup_resp.status_code == 422
    assert src_video.exists()  # Intermediate source video must be preserved!


def test_overlapping_run_prevented_and_cancellation(
    pipeline_client: TestClient, tmp_path: Path
) -> None:
    client = pipeline_client
    dl_dir = tmp_path / "jobs" / "videos"
    dl_dir.mkdir(parents=True, exist_ok=True)
    src_video = dl_dir / "vid_cancel_001.mp4"
    _create_synthetic_video(src_video, duration=3)
    video_id = _seed_video(client, youtube_video_id="vid_cancel_001", local_video_path=src_video)

    # Artificially insert an active run to test 409 overlap prevention.
    repo = PipelineRepository(client.app.state.sessions)  # type: ignore[attr-defined]
    active_run = repo.create_run(trigger_type="manual", target_video_ids=[video_id])
    resp = client.post("/api/v1/pipeline/runs", json={"video_ids": [video_id]})
    assert resp.status_code == 409

    # Cancel the active run.
    cancel_resp = client.post(f"/api/v1/pipeline/runs/{active_run.id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


def test_disk_space_safeguard(
    pipeline_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = pipeline_client
    dl_dir = tmp_path / "jobs" / "videos"
    dl_dir.mkdir(parents=True, exist_ok=True)
    src_video = dl_dir / "vid_disk_001.mp4"
    _create_synthetic_video(src_video, duration=2)
    video_id = _seed_video(client, youtube_video_id="vid_disk_001", local_video_path=src_video)

    # Simulate critically low disk space (10 MB free, threshold 500 MB).
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=100 * 1024**3, used=99 * 1024**3, free=10 * 1024 * 1024
        ),
    )

    resp = client.post("/api/v1/pipeline/runs", json={"video_ids": [video_id]})
    assert resp.status_code == 202
    final = _wait_for_run(client, resp.json()["id"])
    assert final["status"] == "failed"
    assert final["failed_videos"] == 1
    assert "disk space" in (final["last_error"] or "").lower()


def test_scheduler_timezone_and_settings_persistence(pipeline_client: TestClient) -> None:
    client = pipeline_client
    get_resp = client.get("/api/v1/settings/pipeline")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["scheduler_enabled"] is True
    assert data["scheduler_time"] == "03:00"
    assert data["timezone"] == "Asia/Kolkata"
    assert data["pipeline_concurrent_limit"] == 1

    # Update settings and verify persistence + scheduler rescheduling.
    scheduler: PipelineSchedulerService = client.app.state.scheduler_service  # type: ignore[attr-defined]
    scheduler._scheduler.start()
    try:
        updated_payload = {
            "scheduler_enabled": True,
            "scheduler_frequency": "daily",
            "scheduler_time": "04:30",
            "timezone": "Asia/Kolkata",
            "discovery_lookback_days": 10,
            "extraction_interval_seconds": 45.0,
            "pipeline_concurrent_limit": 2,
            "pipeline_retry_attempts": 2,
            "auto_cleanup_enabled": True,
            "min_free_disk_mb": 750,
        }
        put_resp = client.put("/api/v1/settings/pipeline", json=updated_payload)
        assert put_resp.status_code == 200
        assert put_resp.json()["scheduler_time"] == "04:30"
        assert put_resp.json()["discovery_lookback_days"] == 10

        status_resp = client.get("/api/v1/pipeline/scheduler")
        assert status_resp.status_code == 200
        sched_status = status_resp.json()
        assert sched_status["enabled"] is True
        assert sched_status["time"] == "04:30"
        assert sched_status["next_run_at"] is not None
        next_ist = datetime.fromisoformat(sched_status["next_run_at"]).astimezone(
            ZoneInfo("Asia/Kolkata")
        )
        assert next_ist.hour == 4 and next_ist.minute == 30

        job = scheduler._scheduler.get_job(DAILY_JOB_ID)
        assert job is not None
        assert job.coalesce is True
        assert job.max_instances == 1
        assert job.misfire_grace_time == 3600
    finally:
        scheduler.shutdown()


def test_restart_recovery_resumes_incomplete_run(
    pipeline_client: TestClient, tmp_path: Path
) -> None:
    client = pipeline_client
    dl_dir = tmp_path / "jobs" / "videos"
    dl_dir.mkdir(parents=True, exist_ok=True)
    src_video = dl_dir / "vid_recover_001.mp4"
    _create_synthetic_video(src_video, duration=2)
    video_id = _seed_video(client, youtube_video_id="vid_recover_001", local_video_path=src_video)

    repo = PipelineRepository(client.app.state.sessions)  # type: ignore[attr-defined]
    stale_run = repo.create_run(trigger_type="scheduled", target_video_ids=[video_id])
    repo.update_run(stale_run.id, status="running", current_stage="extracting")

    orchestrator: PipelineOrchestrator = client.app.state.pipeline_orchestrator  # type: ignore[attr-defined]
    resumed = orchestrator.recover()
    assert resumed == 1

    final = _wait_for_run(client, stale_run.id)
    assert final["status"] == "completed"
    assert final["completed_videos"] == 1
    assert any("Resuming interrupted pipeline run" in log["message"] for log in final["logs"])
