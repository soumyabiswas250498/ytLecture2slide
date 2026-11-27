"""Tests for video exclusion keywords, Unicode matching, reevaluation, and backend enforcement."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.channels import ChannelCreateInput
from app.domain.downloads import DownloadStatus
from app.domain.exclusion import (
    deduplicate_keywords,
    match_title,
    normalize_keyword,
)
from app.domain.videos import LivestreamStatus
from app.infrastructure.database import create_database_engine, session_factory
from app.main import create_app
from app.repositories.channels import ChannelRepository
from app.repositories.extractions import ExtractionRepository
from app.repositories.slides import SlideRepository
from app.repositories.videos import VideoRepository


def test_unicode_matching_english_and_bengali() -> None:
    # Case-insensitive & punctuation boundaries
    assert match_title("WBPSC IDO Math Class 1", ["math"]).excluded is True
    assert match_title("WBPSC (Math) - Session", ["Math"]).excluded is True
    assert match_title("Math/Reasoning Practice", ["Math", "Reasoning"]).matched_keywords == [
        "Math",
        "Reasoning",
    ]

    # Avoid unintended substring matches inside unrelated words
    assert match_title("Aromatherapy & Wellness", ["Math"]).excluded is False
    assert match_title("Mathematics Class", ["Math"]).excluded is False

    # Multi-word phrases with normalized whitespace
    assert match_title("Number   System  Part 2", ["Number System"]).excluded is True

    # Bengali keywords including matras and anusvara (ং)
    assert match_title("WBPSC গণিত ক্লাস ১", ["গণিত"]).excluded is True
    assert match_title("রিজনিং ক্লাস।", ["রিজনিং"]).excluded is True
    assert match_title("অঙ্ক ও রিজনিং", ["অঙ্ক", "রিজনিং"]).matched_keywords == [
        "অঙ্ক",
        "রিজনিং",
    ]
    assert match_title("ইতিহাস ও ভূগোল", ["গণিত", "অঙ্ক"]).excluded is False


def test_keyword_validation_and_deduplication() -> None:
    with pytest.raises(ValueError, match="empty"):
        normalize_keyword("   ")
    with pytest.raises(ValueError, match="Duplicate"):
        deduplicate_keywords(["Math", "  math  "], reject_duplicates=True)
    assert deduplicate_keywords(["  গণিত ", "গণিত"], reject_duplicates=False) == ["গণিত"]


@pytest.fixture()
def exclusion_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "head")
    app = create_app(Settings())
    with TestClient(app) as client:
        yield client


def _seed_videos(client: TestClient) -> tuple[int, int]:
    sessions = client.app.state.sessions  # type: ignore[attr-defined]
    ch_repo = ChannelRepository(sessions)
    channel = ch_repo.create(
        ChannelCreateInput(
            name="Test Channel",
            channel_url="https://www.youtube.com/@testchannel",
            youtube_channel_id=None,
            sample_video_url=None,
            search_keyword="IDO",
            is_active=True,
        )
    )
    vid_repo = VideoRepository(sessions)
    now = datetime.now(UTC)
    v1, _ = vid_repo.create_or_skip(
        channel_id=channel.id,
        youtube_video_id="vid_gs_00001",
        title="WBPSC IDO General Studies",
        description="",
        video_url="https://www.youtube.com/watch?v=vid_gs_00001",
        thumbnail_url=None,
        duration_seconds=3600,
        published_at=now,
        livestream_status=LivestreamStatus.NONE,
        discovered_at=now,
    )
    v2, _ = vid_repo.create_or_skip(
        channel_id=channel.id,
        youtube_video_id="vid_math_002",
        title="WBPSC IDO গণিত ও Math ক্লাস",
        description="",
        video_url="https://www.youtube.com/watch?v=vid_math_002",
        thumbnail_url=None,
        duration_seconds=3600,
        published_at=now,
        livestream_status=LivestreamStatus.NONE,
        discovered_at=now,
    )
    return v1.id, v2.id


def test_exclusion_crud_reevaluation_and_enforcement(exclusion_client: TestClient) -> None:
    client = exclusion_client
    eligible_id, math_id = _seed_videos(client)

    # Initially empty
    resp = client.get("/api/v1/settings/exclusion-keywords")
    assert resp.status_code == 200
    assert resp.json()["keywords"] == []
    assert "Math" in resp.json()["suggested_keywords"]

    # Reject empty / duplicate via PUT
    bad = client.put("/api/v1/settings/exclusion-keywords", json={"keywords": ["Math", "math"]})
    assert bad.status_code == 422

    # Save English + Bengali keywords -> reevaluates existing videos
    put = client.put(
        "/api/v1/settings/exclusion-keywords",
        json={"keywords": ["Math", "গণিত"]},
    )
    assert put.status_code == 200
    data = put.json()
    assert data["keywords"] == ["Math", "গণিত"]
    assert data["excluded_video_count"] == 1
    assert data["eligible_video_count"] == 1

    # Summary & eligibility filter reflect classification
    summary = client.get("/api/v1/videos/summary").json()
    assert summary["eligible"] == 1
    assert summary["excluded"] == 1

    excluded_list = client.get("/api/v1/videos?eligibility=excluded").json()
    assert excluded_list["total"] == 1
    assert excluded_list["items"][0]["id"] == math_id
    assert excluded_list["items"][0]["is_excluded"] is True
    assert excluded_list["items"][0]["excluded_keywords"] == ["Math", "গণিত"]

    # Backend enforcement: individual download, extraction, slides blocked
    dl_resp = client.post(f"/api/v1/videos/{math_id}/download")
    assert dl_resp.status_code == 409
    assert dl_resp.json()["error"]["code"] == "video_excluded"

    ext_resp = client.post(f"/api/v1/videos/{math_id}/extraction", json={})
    assert ext_resp.status_code == 409

    slide_resp = client.post(f"/api/v1/videos/{math_id}/slide-processing", json={})
    assert slide_resp.status_code == 409

    # Mixed bulk download skips excluded video with explanation
    bulk_dl = client.post(
        "/api/v1/videos/downloads/bulk",
        json={"video_ids": [math_id, 999999]},
    )
    assert bulk_dl.status_code == 202
    assert any(
        item["video_id"] == math_id and "Math" in item["reason"]
        for item in bulk_dl.json()["skipped"]
    )

    # Mixed bulk extraction & slides report excluded error
    bulk_ext = client.post(
        "/api/v1/videos/extractions/bulk",
        json={"video_ids": [math_id, eligible_id]},
    )
    assert bulk_ext.status_code == 202
    assert any(
        item["video_id"] == math_id and "Excluded" in item["reason"]
        for item in bulk_ext.json()["errors"]
    )

    bulk_slides = client.post(
        "/api/v1/videos/slides/bulk",
        json={"video_ids": [math_id, eligible_id]},
    )
    assert bulk_slides.status_code == 202
    assert any(
        item["video_id"] == math_id and "Excluded" in item["reason"]
        for item in bulk_slides.json()["errors"]
    )

    # Removing keywords restores eligibility
    clear_resp = client.put("/api/v1/settings/exclusion-keywords", json={"keywords": []})
    assert clear_resp.status_code == 200
    assert clear_resp.json()["excluded_video_count"] == 0
    assert clear_resp.json()["eligible_video_count"] == 2
    vid_after = client.get(f"/api/v1/videos/{math_id}").json()
    assert vid_after["is_excluded"] is False
    assert vid_after["excluded_keywords"] == []


def test_pending_job_recovery_skips_excluded_videos_without_deleting_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "recover.db"))
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(cfg, "head")

    engine = create_database_engine(tmp_path / "recover.db")
    sessions = session_factory(engine)
    vid_repo = VideoRepository(sessions)
    now = datetime.now(UTC)
    v, _ = vid_repo.create_or_skip(
        channel_id=None,
        youtube_video_id="vid_rec_0001",
        title="Math Recovery Test",
        description="",
        video_url="https://www.youtube.com/watch?v=vid_rec_0001",
        thumbnail_url=None,
        duration_seconds=3600,
        published_at=now,
        livestream_status=LivestreamStatus.NONE,
        discovered_at=now,
        is_excluded=True,
        excluded_keywords=["Math"],
    )
    # Simulate pending recovery intent for download, extraction, and slides
    vid_repo.update_download_state(
        v.id,
        download_status=DownloadStatus.DOWNLOADING,
        download_requested=True,
    )
    ext_repo = ExtractionRepository(sessions)
    ext_repo.claim(v.id, 60.0)
    slide_repo = SlideRepository(sessions)
    from app.domain.slides import SlideConfig

    slide_repo.claim(v.id, SlideConfig())
    engine.dispose()

    # App startup recovery must cancel/block excluded jobs instead of running them
    app = create_app(Settings())
    with TestClient(app):
        assert vid_repo.get_by_id(v.id) is not None
        assert not vid_repo.get_by_id(v.id).download_requested  # type: ignore[union-attr]
        assert not ext_repo.get(v.id).requested
        assert not slide_repo.get(v.id).requested
