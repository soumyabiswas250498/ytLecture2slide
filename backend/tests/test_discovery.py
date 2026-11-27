"""Tests for the YouTube API client, discovery service and video repository.

All YouTube API calls are mocked — no live network required.
Uses unittest.mock.patch for httpx responses.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.videos import (
    DiscoveryAlreadyRunningError,
    LivestreamStatus,
    ProcessingStatus,
    QuotaExhaustedError,
)
from app.infrastructure.youtube_client import (
    QUOTA_RESET_TIMEZONE,
    YouTubeApiClient,
    next_quota_reset_utc,
)
from app.main import create_app
from app.repositories.channels import ChannelRepository
from app.repositories.videos import VideoRepository
from app.services.discovery import DiscoveryService, _parse_duration_seconds

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def migrated_discovery_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "database" / "app.db"))
    monkeypatch.setenv("TEMP_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-api-key-00000000000000000000000000000000")
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    settings = Settings(_env_file=None)
    with TestClient(create_app(settings), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def migrated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "database" / "app.db"))
    monkeypatch.setenv("TEMP_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-api-key-00000000000000000000000000000000")
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    return Settings(_env_file=None)


def _make_sessions(settings: Settings):  # type: ignore[no-untyped-def]
    from app.infrastructure.database import create_database_engine, session_factory

    engine = create_database_engine(settings.database_path)  # type: ignore[arg-type]
    return session_factory(engine)


def _build_video_item(
    video_id: str,
    title: str = "Test Lecture",
    duration: str = "PT2H",
    channel_id: str = "UCtest00000000000000000001",
    livestream: str = "none",
    published: str = "2025-01-01T10:00:00Z",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": video_id,
        "snippet": {
            "title": title,
            "description": "A test description.",
            "channelId": channel_id,
            "publishedAt": published,
            "liveBroadcastContent": livestream,
            "thumbnails": {"high": {"url": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"}},
        },
        "contentDetails": {"duration": duration},
        "liveStreamingDetails": {},
    }
    return item


# ---------------------------------------------------------------------------
# _parse_duration_seconds
# ---------------------------------------------------------------------------


class TestParseDurationSeconds:
    def test_parse_hours_minutes_seconds(self) -> None:
        assert _parse_duration_seconds("PT1H23M45S") == 5025

    def test_parse_minutes_only(self) -> None:
        assert _parse_duration_seconds("PT30M") == 1800

    def test_parse_hours_only(self) -> None:
        assert _parse_duration_seconds("PT2H") == 7200

    def test_parse_zero(self) -> None:
        assert _parse_duration_seconds("PT0S") == 0

    def test_parse_invalid_returns_zero(self) -> None:
        assert _parse_duration_seconds("INVALID") == 0

    def test_parse_empty_returns_zero(self) -> None:
        assert _parse_duration_seconds("") == 0


# ---------------------------------------------------------------------------
# YouTubeApiClient unit tests (httpx mocked)
# ---------------------------------------------------------------------------


class TestYouTubeApiClientQuota:
    def test_quota_exhausted_before_request(self) -> None:
        client = YouTubeApiClient("key", quota_limit=0)
        with pytest.raises(QuotaExhaustedError):
            client.resolve_channel_by_handle("@test")

    def test_separate_search_quota_bucket(self) -> None:
        import httpx

        client = YouTubeApiClient("key", quota_limit=10000, search_quota_limit=1)
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"items": []}

        with patch.object(client._client, "get", return_value=mock_resp):
            client.search_videos("UCtest", "IDO", datetime.now(UTC))
            assert client.search_quota_used == 1
            assert client.search_quota_remaining == 0
            assert client.quota_used == 0
            # Second search.list call must fail even though general pool has 10000 left.
            with pytest.raises(QuotaExhaustedError, match="America/Los_Angeles"):
                client.search_videos("UCtest", "IDO", datetime.now(UTC))
            # General pool call (channels.list) still succeeds.
            client.resolve_channel_by_handle("@test")
            assert client.quota_used == 1

    def test_retry_and_pagination_count_toward_quota(self) -> None:
        import httpx

        client = YouTubeApiClient("key", max_retries=2, quota_limit=100, search_quota_limit=100)
        resp_500 = MagicMock(spec=httpx.Response)
        resp_500.status_code = 500
        resp_ok_p1 = MagicMock(spec=httpx.Response)
        resp_ok_p1.status_code = 200
        resp_ok_p1.json.return_value = {"items": [], "nextPageToken": "P2"}
        resp_ok_p2 = MagicMock(spec=httpx.Response)
        resp_ok_p2.status_code = 200
        resp_ok_p2.json.return_value = {"items": []}

        with (
            patch.object(client._client, "get", side_effect=[resp_500, resp_ok_p1, resp_ok_p2]),
            patch("app.infrastructure.youtube_client.time.sleep"),
        ):
            _, tok1 = client.search_videos("UCtest", "IDO", datetime.now(UTC))
            assert tok1 == "P2"
            _, tok2 = client.search_videos("UCtest", "IDO", datetime.now(UTC), page_token=tok1)
            assert tok2 is None
        # 1 failed retry + 2 successful paginated pages = 3 search requests.
        assert client.search_quota_used == 3
        assert client.requests_made == 3

    def test_next_quota_reset_utc_is_midnight_pacific(self) -> None:
        sample = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
        reset = next_quota_reset_utc(sample)
        reset_pt = reset.astimezone(QUOTA_RESET_TIMEZONE)
        assert reset_pt.hour == 0
        assert reset_pt.minute == 0
        assert reset_pt.second == 0
        assert reset_pt.date() > sample.astimezone(QUOTA_RESET_TIMEZONE).date()

    def test_repr_does_not_expose_key(self) -> None:
        client = YouTubeApiClient("SUPER_SECRET_KEY", quota_limit=9000)
        assert "SUPER_SECRET_KEY" not in repr(client)

    def test_api_key_never_exposed_in_errors_or_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import httpx

        from app.domain.videos import ChannelResolutionError

        secret = "SECRET_TEST_KEY_99999"
        client = YouTubeApiClient(secret, max_retries=1)
        req = httpx.Request("GET", f"https://www.googleapis.com/youtube/v3/channels?key={secret}")
        with (
            caplog.at_level("WARNING"),
            patch.object(
                client._client,
                "get",
                side_effect=httpx.ConnectError(f"Failed connecting to {req.url}", request=req),
            ),
            pytest.raises(ChannelResolutionError) as exc_info,
        ):
            client.resolve_channel_by_handle("@test")
        assert secret not in str(exc_info.value)
        assert secret not in caplog.text


class TestYouTubeApiClientResolveHandle:
    def test_resolve_handle_success(self) -> None:
        client = YouTubeApiClient("key")
        with patch.object(
            client,
            "_get",
            return_value={"items": [{"id": "UCtest00000000000000000001"}]},
        ):
            result = client.resolve_channel_by_handle("@testchannel")
        assert result == "UCtest00000000000000000001"

    def test_resolve_handle_not_found(self) -> None:
        client = YouTubeApiClient("key")
        with patch.object(client, "_get", return_value={"items": []}):
            result = client.resolve_channel_by_handle("@unknown")
        assert result is None

    def test_resolve_username_success(self) -> None:
        client = YouTubeApiClient("key")
        with patch.object(
            client,
            "_get",
            return_value={"items": [{"id": "UCtest00000000000000000002"}]},
        ):
            result = client.resolve_channel_by_username("legacyuser")
        assert result == "UCtest00000000000000000002"


class TestYouTubeApiClientChannelId:
    def test_resolve_channel_by_id_exists(self) -> None:
        client = YouTubeApiClient("key")
        with patch.object(client, "_get", return_value={"items": [{"id": "UCtest"}]}):
            assert client.resolve_channel_by_id("UCtest") is True

    def test_resolve_channel_by_id_missing(self) -> None:
        client = YouTubeApiClient("key")
        with patch.object(client, "_get", return_value={"items": []}):
            assert client.resolve_channel_by_id("UCmissing") is False


class TestYouTubeApiClientSearchVideos:
    def test_search_videos_returns_items_and_token(self) -> None:
        client = YouTubeApiClient("key")
        fake_items = [{"id": {"videoId": "abc123"}}]
        with patch.object(
            client,
            "_get",
            return_value={"items": fake_items, "nextPageToken": "TOKEN123"},
        ):
            items, token = client.search_videos("UCtest", "lecture", datetime.now(UTC))
        assert items == fake_items
        assert token == "TOKEN123"

    def test_search_videos_no_next_token(self) -> None:
        client = YouTubeApiClient("key")
        with patch.object(client, "_get", return_value={"items": []}):
            items, token = client.search_videos("UCtest", "lecture", datetime.now(UTC))
        assert items == []
        assert token is None


class TestYouTubeApiClientGetVideosDetails:
    def test_get_videos_details_batches_up_to_50(self) -> None:
        client = YouTubeApiClient("key")
        # 51 IDs should trigger two API calls.
        video_ids = [f"vid{i:05d}" for i in range(51)]
        call_count = 0

        def fake_get(
            endpoint: str, params: dict[str, str], *, quota_cost: int, is_search: bool = False
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"items": []}

        with patch.object(client, "_get", side_effect=fake_get):
            client.get_videos_details(video_ids)
        assert call_count == 2

    def test_get_videos_details_empty_list(self) -> None:
        client = YouTubeApiClient("key")
        result = client.get_videos_details([])
        assert result == []


class TestYouTubeApiClientHttpErrors:
    def _make_client(self) -> YouTubeApiClient:
        return YouTubeApiClient("key", max_retries=1)

    def test_quota_exceeded_403(self) -> None:
        import httpx

        client = self._make_client()
        quota_body = {
            "error": {
                "message": "Daily Limit Exceeded",
                "errors": [{"reason": "quotaExceeded"}],
            }
        }
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 403
        mock_resp.json.return_value = quota_body
        with (
            patch.object(client._client, "get", return_value=mock_resp),
            pytest.raises(QuotaExhaustedError),
        ):
            client._get("channels", {"part": "id"}, quota_cost=1)

    def test_invalid_credentials_401(self) -> None:
        import httpx

        from app.domain.videos import ChannelResolutionError

        client = self._make_client()
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        with (
            patch.object(client._client, "get", return_value=mock_resp),
            pytest.raises(ChannelResolutionError, match="credentials are invalid"),
        ):
            client._get("channels", {"part": "id"}, quota_cost=1)


# ---------------------------------------------------------------------------
# VideoRepository tests
# ---------------------------------------------------------------------------


class TestVideoRepository:
    def test_create_or_skip_new_video(self, migrated_settings: Settings) -> None:
        sessions = _make_sessions(migrated_settings)
        repo = VideoRepository(sessions)
        entity, created = repo.create_or_skip(
            channel_id=None,
            youtube_video_id="testvid0001",
            title="Test Lecture",
            description="Desc",
            video_url="https://www.youtube.com/watch?v=testvid0001",
            thumbnail_url=None,
            duration_seconds=5000,
            published_at=datetime.now(UTC),
            livestream_status=LivestreamStatus.NONE,
            discovered_at=datetime.now(UTC),
        )
        assert created is True
        assert entity.youtube_video_id == "testvid0001"
        assert entity.processing_status == ProcessingStatus.PENDING

    def test_create_or_skip_duplicate_does_not_reset_status(
        self, migrated_settings: Settings
    ) -> None:
        sessions = _make_sessions(migrated_settings)
        repo = VideoRepository(sessions)
        repo.create_or_skip(
            channel_id=None,
            youtube_video_id="testvid0002",
            title="First",
            description="",
            video_url="https://www.youtube.com/watch?v=testvid0002",
            thumbnail_url=None,
            duration_seconds=5000,
            published_at=datetime.now(UTC),
            livestream_status=LivestreamStatus.NONE,
            discovered_at=datetime.now(UTC),
        )
        entity2, created2 = repo.create_or_skip(
            channel_id=None,
            youtube_video_id="testvid0002",
            title="Second",
            description="",
            video_url="https://www.youtube.com/watch?v=testvid0002",
            thumbnail_url=None,
            duration_seconds=5000,
            published_at=datetime.now(UTC),
            livestream_status=LivestreamStatus.NONE,
            discovered_at=datetime.now(UTC),
        )
        assert created2 is False
        # Title must still be the original; processing_status must remain pending.
        assert entity2.title == "First"
        assert entity2.processing_status == ProcessingStatus.PENDING

    def test_get_by_id_returns_none_for_missing(self, migrated_settings: Settings) -> None:
        sessions = _make_sessions(migrated_settings)
        repo = VideoRepository(sessions)
        assert repo.get_by_id(99999) is None

    def test_find_by_youtube_id_returns_none_for_missing(self, migrated_settings: Settings) -> None:
        sessions = _make_sessions(migrated_settings)
        repo = VideoRepository(sessions)
        assert repo.find_by_youtube_id("nomatch") is None

    def test_list_videos_pagination(self, migrated_settings: Settings) -> None:
        sessions = _make_sessions(migrated_settings)
        repo = VideoRepository(sessions)
        for i in range(5):
            repo.create_or_skip(
                channel_id=None,
                youtube_video_id=f"pagevid{i:04d}",
                title=f"Video {i}",
                description="",
                video_url=f"https://www.youtube.com/watch?v=pagevid{i:04d}",
                thumbnail_url=None,
                duration_seconds=5000 + i,
                published_at=datetime.now(UTC),
                livestream_status=LivestreamStatus.NONE,
                discovered_at=datetime.now(UTC),
            )
        page = repo.list_videos(page=1, page_size=2)
        assert page.total == 5
        assert len(page.items) == 2
        assert page.total_pages == 3

    def test_list_videos_search_filter(self, migrated_settings: Settings) -> None:
        sessions = _make_sessions(migrated_settings)
        repo = VideoRepository(sessions)
        repo.create_or_skip(
            channel_id=None,
            youtube_video_id="searchvid001",
            title="বাংলা লেকচার",
            description="",
            video_url="https://www.youtube.com/watch?v=searchvid001",
            thumbnail_url=None,
            duration_seconds=5000,
            published_at=datetime.now(UTC),
            livestream_status=LivestreamStatus.NONE,
            discovered_at=datetime.now(UTC),
        )
        repo.create_or_skip(
            channel_id=None,
            youtube_video_id="searchvid002",
            title="English lecture",
            description="",
            video_url="https://www.youtube.com/watch?v=searchvid002",
            thumbnail_url=None,
            duration_seconds=5000,
            published_at=datetime.now(UTC),
            livestream_status=LivestreamStatus.NONE,
            discovered_at=datetime.now(UTC),
        )
        page = repo.list_videos(search="বাংলা")
        assert page.total == 1
        assert page.items[0].youtube_video_id == "searchvid001"

    def test_list_videos_processing_status_filter(self, migrated_settings: Settings) -> None:
        sessions = _make_sessions(migrated_settings)
        repo = VideoRepository(sessions)
        repo.create_or_skip(
            channel_id=None,
            youtube_video_id="filtervid001",
            title="Pending video",
            description="",
            video_url="https://www.youtube.com/watch?v=filtervid001",
            thumbnail_url=None,
            duration_seconds=5000,
            published_at=datetime.now(UTC),
            livestream_status=LivestreamStatus.NONE,
            discovered_at=datetime.now(UTC),
        )
        page = repo.list_videos(processing_status=ProcessingStatus.PENDING)
        assert page.total >= 1
        assert all(v.processing_status == ProcessingStatus.PENDING for v in page.items)

    def test_get_summary_counts_today(self, migrated_settings: Settings) -> None:
        sessions = _make_sessions(migrated_settings)
        repo = VideoRepository(sessions)
        repo.create_or_skip(
            channel_id=None,
            youtube_video_id="summaryvid001",
            title="Today's lecture",
            description="",
            video_url="https://www.youtube.com/watch?v=summaryvid001",
            thumbnail_url=None,
            duration_seconds=5000,
            published_at=datetime.now(UTC),
            livestream_status=LivestreamStatus.NONE,
            discovered_at=datetime.now(UTC),
        )
        summary = repo.get_summary()
        assert summary.total >= 1
        assert summary.pending >= 1
        assert summary.today >= 1
        assert summary.latest_discovery_at is not None

    def test_list_videos_date_range_filter(self, migrated_settings: Settings) -> None:
        sessions = _make_sessions(migrated_settings)
        repo = VideoRepository(sessions)
        old_date = datetime(2024, 1, 1, tzinfo=UTC)
        new_date = datetime(2025, 6, 1, tzinfo=UTC)
        repo.create_or_skip(
            channel_id=None,
            youtube_video_id="datevid001",
            title="Old video",
            description="",
            video_url="https://www.youtube.com/watch?v=datevid001",
            thumbnail_url=None,
            duration_seconds=5000,
            published_at=old_date,
            livestream_status=LivestreamStatus.NONE,
            discovered_at=datetime.now(UTC),
        )
        repo.create_or_skip(
            channel_id=None,
            youtube_video_id="datevid002",
            title="New video",
            description="",
            video_url="https://www.youtube.com/watch?v=datevid002",
            thumbnail_url=None,
            duration_seconds=5000,
            published_at=new_date,
            livestream_status=LivestreamStatus.NONE,
            discovered_at=datetime.now(UTC),
        )
        page = repo.list_videos(published_after=datetime(2025, 1, 1, tzinfo=UTC))
        ids = [v.youtube_video_id for v in page.items]
        assert "datevid002" in ids
        assert "datevid001" not in ids


# ---------------------------------------------------------------------------
# DiscoveryService unit tests (YouTube client fully mocked)
# ---------------------------------------------------------------------------


def _build_service(settings: Settings) -> tuple[DiscoveryService, MagicMock]:
    sessions = _make_sessions(settings)
    mock_yt = MagicMock(spec=YouTubeApiClient)
    mock_yt.quota_used = 0
    channel_repo = ChannelRepository(sessions)
    video_repo = VideoRepository(sessions)
    service = DiscoveryService(
        youtube_client=mock_yt,
        channel_repo=channel_repo,
        video_repo=video_repo,
        settings=settings,
    )
    return service, mock_yt


def _create_channel(settings: Settings, *, youtube_channel_id: str | None = None) -> int:
    from app.services.channels import ChannelService

    sessions = _make_sessions(settings)
    repo = ChannelRepository(sessions)
    svc = ChannelService(repository=repo, default_search_keyword="IDO")
    channel = svc.create_channel(
        name="Test Channel",
        channel_url=(
            f"https://www.youtube.com/channel/{youtube_channel_id}"
            if youtube_channel_id
            else "https://www.youtube.com/@testchannel"
        ),
        youtube_channel_id=youtube_channel_id,
        is_active=True,
    )
    return channel.id


class TestDiscoveryServiceChannelResolution:
    def test_discover_already_resolved_channel_id_skips_lookup(
        self, migrated_settings: Settings
    ) -> None:
        channel_id = _create_channel(
            migrated_settings, youtube_channel_id="UCtest00000000000000000001"
        )
        service, mock_yt = _build_service(migrated_settings)
        mock_yt.search_videos.return_value = ([], None)
        summary = service.discover_one_channel(channel_id)
        mock_yt.resolve_channel_by_id.assert_not_called()
        mock_yt.resolve_channel_by_handle.assert_not_called()
        assert summary.channels_checked == 1

    def test_discover_handle_url_resolves_via_handle(self, migrated_settings: Settings) -> None:
        # @testchannel → handle resolution
        channel_id = _create_channel(migrated_settings)
        service, mock_yt = _build_service(migrated_settings)
        mock_yt.resolve_channel_by_handle.return_value = "UCtest00000000000000000099"
        mock_yt.search_videos.return_value = ([], None)
        summary = service.discover_one_channel(channel_id)
        mock_yt.resolve_channel_by_handle.assert_called_once()
        assert summary.channels_checked == 1
        assert not summary.failed_channels

    def test_unresolvable_channel_reported_as_failed(self, migrated_settings: Settings) -> None:
        channel_id = _create_channel(migrated_settings)
        service, mock_yt = _build_service(migrated_settings)
        mock_yt.resolve_channel_by_handle.return_value = None
        summary = service.discover_one_channel(channel_id)
        assert len(summary.failed_channels) == 1

    def test_inactive_channel_skipped(self, migrated_settings: Settings) -> None:
        from app.services.channels import ChannelService

        sessions = _make_sessions(migrated_settings)
        repo = ChannelRepository(sessions)
        svc = ChannelService(repository=repo, default_search_keyword="IDO")
        ch = svc.create_channel(
            name="Inactive",
            channel_url="https://www.youtube.com/@inactive",
            is_active=False,
        )
        service, mock_yt = _build_service(migrated_settings)
        summary = service.discover_one_channel(ch.id)
        assert summary.channels_skipped == 1
        mock_yt.search_videos.assert_not_called()


class TestDiscoveryServiceVideoFiltering:
    def _setup(
        self, migrated_settings: Settings, *, youtube_channel_id: str = "UCtest00000000000000000001"
    ) -> tuple[DiscoveryService, MagicMock, int]:
        channel_db_id = _create_channel(migrated_settings, youtube_channel_id=youtube_channel_id)
        service, mock_yt = _build_service(migrated_settings)
        return service, mock_yt, channel_db_id

    def test_video_below_min_duration_rejected(self, migrated_settings: Settings) -> None:
        service, mock_yt, channel_db_id = self._setup(migrated_settings)
        short_video = _build_video_item("shortv001", duration="PT10M")  # 600s <= 1200s
        mock_yt.search_videos.return_value = ([{"id": {"videoId": "shortv001"}}], None)
        mock_yt.get_videos_details.return_value = [short_video]
        summary = service.discover_one_channel(channel_db_id)
        assert summary.videos_rejected_duration == 1
        assert summary.new_videos_added == 0

    def test_video_exact_1200s_rejected_and_1201s_accepted(
        self, migrated_settings: Settings
    ) -> None:
        service, mock_yt, channel_db_id = self._setup(migrated_settings)
        exact_20m = _build_video_item("exact1200", duration="PT20M")  # 1200s -> rejected
        over_20m = _build_video_item("over1201", duration="PT20M1S")  # 1201s -> accepted
        mock_yt.search_videos.return_value = (
            [{"id": {"videoId": "exact1200"}}, {"id": {"videoId": "over1201"}}],
            None,
        )
        mock_yt.get_videos_details.return_value = [exact_20m, over_20m]
        summary = service.discover_one_channel(channel_db_id)
        assert summary.videos_rejected_duration == 1
        assert summary.new_videos_added == 1

    def test_deferred_livestream_rediscovered_when_completed(
        self, migrated_settings: Settings
    ) -> None:
        service, mock_yt, channel_db_id = self._setup(migrated_settings)
        live_vid = _build_video_item("stream001", duration="PT2H", livestream="live")
        mock_yt.search_videos.return_value = ([{"id": {"videoId": "stream001"}}], None)
        mock_yt.get_videos_details.return_value = [live_vid]
        s1 = service.discover_one_channel(channel_db_id)
        assert s1.livestreams_deferred == 1
        assert s1.new_videos_added == 0

        # Run 2: stream has completed.
        completed_vid: dict[str, Any] = {
            "id": "stream001",
            "snippet": {
                "title": "Completed Stream",
                "description": "",
                "channelId": "UCtest00000000000000000001",
                "publishedAt": "2025-01-01T10:00:00Z",
                "liveBroadcastContent": "none",
                "thumbnails": {},
            },
            "contentDetails": {"duration": "PT2H"},
            "liveStreamingDetails": {"actualEndTime": "2025-01-01T12:00:00Z"},
        }
        mock_yt.search_videos.return_value = ([{"id": {"videoId": "stream001"}}], None)
        mock_yt.get_videos_details.return_value = [completed_vid]
        s2 = service.discover_one_channel(channel_db_id)
        assert s2.new_videos_added == 1
        repo = VideoRepository(_make_sessions(migrated_settings))
        saved = repo.find_by_youtube_id("stream001")
        assert saved is not None
        assert saved.livestream_status == LivestreamStatus.COMPLETED
        assert saved.processing_status == ProcessingStatus.PENDING

    def test_duplicate_canonical_channel_id_rejected_on_resolution(
        self, migrated_settings: Settings
    ) -> None:
        from app.services.channels import ChannelService

        sessions = _make_sessions(migrated_settings)
        ch_svc = ChannelService(
            repository=ChannelRepository(sessions), default_search_keyword="IDO"
        )
        ch_svc.create_channel(
            name="Canonical Channel",
            channel_url="https://www.youtube.com/channel/UCdup00000000000000000001",
            youtube_channel_id="UCdup00000000000000000001",
            is_active=True,
        )
        handle_ch = ch_svc.create_channel(
            name="Duplicate Handle",
            channel_url="https://www.youtube.com/@duphandle",
            is_active=True,
        )
        service, mock_yt = _build_service(migrated_settings)
        mock_yt.resolve_channel_by_handle.return_value = "UCdup00000000000000000001"
        summary = service.discover_one_channel(handle_ch.id)
        assert "Duplicate Handle" in summary.failed_channels
        mock_yt.search_videos.assert_not_called()

    def test_video_above_min_duration_persisted(self, migrated_settings: Settings) -> None:
        service, mock_yt, channel_db_id = self._setup(migrated_settings)
        long_video = _build_video_item("longv001", duration="PT2H")  # 7200s > 1201s
        mock_yt.search_videos.return_value = ([{"id": {"videoId": "longv001"}}], None)
        mock_yt.get_videos_details.return_value = [long_video]
        summary = service.discover_one_channel(channel_db_id)
        assert summary.new_videos_added == 1

    def test_upcoming_livestream_deferred(self, migrated_settings: Settings) -> None:
        service, mock_yt, channel_db_id = self._setup(migrated_settings)
        upcoming = _build_video_item("upcomingv001", duration="PT2H", livestream="upcoming")
        mock_yt.search_videos.return_value = ([{"id": {"videoId": "upcomingv001"}}], None)
        mock_yt.get_videos_details.return_value = [upcoming]
        summary = service.discover_one_channel(channel_db_id)
        assert summary.livestreams_deferred == 1
        assert summary.new_videos_added == 0

    def test_live_livestream_deferred(self, migrated_settings: Settings) -> None:
        service, mock_yt, channel_db_id = self._setup(migrated_settings)
        live_vid = _build_video_item("livev001", duration="PT2H", livestream="live")
        mock_yt.search_videos.return_value = ([{"id": {"videoId": "livev001"}}], None)
        mock_yt.get_videos_details.return_value = [live_vid]
        summary = service.discover_one_channel(channel_db_id)
        assert summary.livestreams_deferred == 1
        assert summary.new_videos_added == 0

    def test_completed_livestream_included(self, migrated_settings: Settings) -> None:
        service, mock_yt, channel_db_id = self._setup(migrated_settings)
        # none liveBroadcastContent + liveStreamingDetails present → COMPLETED
        completed: dict[str, Any] = {
            "id": "completedv001",
            "snippet": {
                "title": "Completed Livestream",
                "description": "",
                "channelId": "UCtest00000000000000000001",
                "publishedAt": "2025-01-01T10:00:00Z",
                "liveBroadcastContent": "none",
                "thumbnails": {},
            },
            "contentDetails": {"duration": "PT3H"},
            "liveStreamingDetails": {"actualEndTime": "2025-01-01T13:00:00Z"},
        }
        mock_yt.search_videos.return_value = (
            [{"id": {"videoId": "completedv001"}}],
            None,
        )
        mock_yt.get_videos_details.return_value = [completed]
        summary = service.discover_one_channel(channel_db_id)
        assert summary.new_videos_added == 1

    def test_duplicate_video_skipped_on_second_run(self, migrated_settings: Settings) -> None:
        service, mock_yt, channel_db_id = self._setup(migrated_settings)
        vid = _build_video_item("dupv001", duration="PT2H")
        mock_yt.search_videos.return_value = ([{"id": {"videoId": "dupv001"}}], None)
        mock_yt.get_videos_details.return_value = [vid]
        s1 = service.discover_one_channel(channel_db_id)
        assert s1.new_videos_added == 1

        # Reset mock for second run.
        mock_yt.search_videos.return_value = ([{"id": {"videoId": "dupv001"}}], None)
        mock_yt.get_videos_details.return_value = [vid]
        s2 = service.discover_one_channel(channel_db_id)
        assert s2.new_videos_added == 0
        assert s2.existing_videos_skipped == 1

    def test_processing_status_not_reset_on_duplicate(self, migrated_settings: Settings) -> None:
        """Existing processing_status must survive a repeated discovery run."""
        service, mock_yt, channel_db_id = self._setup(migrated_settings)
        vid = _build_video_item("statusv001", duration="PT2H")
        mock_yt.search_videos.return_value = ([{"id": {"videoId": "statusv001"}}], None)
        mock_yt.get_videos_details.return_value = [vid]
        service.discover_one_channel(channel_db_id)

        # Verify video exists with PENDING status.
        sessions = _make_sessions(migrated_settings)
        repo = VideoRepository(sessions)
        entity = repo.find_by_youtube_id("statusv001")
        assert entity is not None
        assert entity.processing_status == ProcessingStatus.PENDING

        # Second run must not reset it.
        mock_yt.search_videos.return_value = ([{"id": {"videoId": "statusv001"}}], None)
        mock_yt.get_videos_details.return_value = [vid]
        service.discover_one_channel(channel_db_id)
        entity2 = repo.find_by_youtube_id("statusv001")
        assert entity2 is not None
        assert entity2.processing_status == ProcessingStatus.PENDING

    def test_pagination_handled(self, migrated_settings: Settings) -> None:
        """Discovery must follow pagination tokens."""
        service, mock_yt, channel_db_id = self._setup(migrated_settings)
        vid1 = _build_video_item("pagev001", duration="PT2H")
        vid2 = _build_video_item("pagev002", duration="PT2H")
        # First call returns a next token; second call does not.
        mock_yt.search_videos.side_effect = [
            ([{"id": {"videoId": "pagev001"}}], "NEXT_PAGE"),
            ([{"id": {"videoId": "pagev002"}}], None),
        ]
        mock_yt.get_videos_details.side_effect = [[vid1], [vid2]]
        summary = service.discover_one_channel(channel_db_id)
        assert summary.new_videos_added == 2
        assert mock_yt.search_videos.call_count == 2


class TestDiscoveryServiceQuota:
    def test_quota_exhausted_stops_gracefully(self, migrated_settings: Settings) -> None:
        channel_db_id = _create_channel(
            migrated_settings, youtube_channel_id="UCtest00000000000000000001"
        )
        service, mock_yt = _build_service(migrated_settings)
        mock_yt.search_videos.side_effect = QuotaExhaustedError("Quota exhausted")
        summary = service.discover_one_channel(channel_db_id)
        assert any("Quota" in e or "quota" in e.lower() for e in summary.errors)

    def test_partial_discovery_one_channel_fails_others_succeed(
        self, migrated_settings: Settings
    ) -> None:
        # Register two channels.
        from app.services.channels import ChannelService

        sessions = _make_sessions(migrated_settings)
        repo = ChannelRepository(sessions)
        svc = ChannelService(repository=repo, default_search_keyword="IDO")
        ch1 = svc.create_channel(
            name="Channel A",
            channel_url="https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaaaa",
            youtube_channel_id="UCaaaaaaaaaaaaaaaaaaaaaaaa",
            is_active=True,
        )
        ch2 = svc.create_channel(
            name="Channel B",
            channel_url="https://www.youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbbbb",
            youtube_channel_id="UCbbbbbbbbbbbbbbbbbbbbbbbb",
            is_active=True,
        )

        _, mock_yt = _build_service(migrated_settings)
        service = DiscoveryService(
            youtube_client=mock_yt,
            channel_repo=ChannelRepository(_make_sessions(migrated_settings)),
            video_repo=VideoRepository(_make_sessions(migrated_settings)),
            settings=migrated_settings,
        )
        vid = _build_video_item(
            "partial001", duration="PT2H", channel_id="UCbbbbbbbbbbbbbbbbbbbbbbbb"
        )

        def search_side_effect(
            channel_id: str, keyword: str, published_after: datetime, **kw: object
        ) -> tuple[list[Any], None]:
            if channel_id == "UCaaaaaaaaaaaaaaaaaaaaaaaa":
                from app.domain.videos import ChannelResolutionError

                raise ChannelResolutionError("Error for channel A")
            return ([{"id": {"videoId": "partial001"}}], None)

        mock_yt.search_videos.side_effect = search_side_effect
        mock_yt.get_videos_details.return_value = [vid]
        mock_yt.quota_used = 0

        summary = service.discover_all_channels()
        assert ch1.id is not None and ch2.id is not None
        assert "Channel A" in summary.failed_channels
        assert summary.new_videos_added >= 1


class TestDiscoveryServiceLock:
    def test_concurrent_run_raises(self, migrated_settings: Settings) -> None:
        import app.services.discovery as disc_module

        disc_module._discovery_running = False  # ensure clean state
        service, mock_yt = _build_service(migrated_settings)

        def _slow_search(*a: object, **kw: object) -> tuple[list[Any], None]:
            time.sleep(0.2)
            return ([], None)

        mock_yt.search_videos.side_effect = _slow_search
        mock_yt.quota_used = 0

        channel_db_id = _create_channel(
            migrated_settings, youtube_channel_id="UCtest00000000000000000001"
        )
        errors: list[Exception] = []

        def run() -> None:
            try:
                service.discover_one_channel(channel_db_id)
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=run)
        t2 = threading.Thread(target=run)
        t1.start()
        time.sleep(0.05)  # ensure t1 acquires lock first
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)
        # At least one thread should have raised DiscoveryAlreadyRunningError.
        assert any(isinstance(e, DiscoveryAlreadyRunningError) for e in errors)
        disc_module._discovery_running = False  # clean up for other tests


# ---------------------------------------------------------------------------
# API endpoint integration tests
# ---------------------------------------------------------------------------


class TestVideoApiEndpoints:
    def test_get_video_summary(self, migrated_discovery_client: TestClient) -> None:
        response = migrated_discovery_client.get("/api/v1/videos/summary")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "pending" in data
        assert "today" in data

    def test_list_videos_empty(self, migrated_discovery_client: TestClient) -> None:
        response = migrated_discovery_client.get("/api/v1/videos")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_videos_pagination_params(self, migrated_discovery_client: TestClient) -> None:
        response = migrated_discovery_client.get(
            "/api/v1/videos?page=1&page_size=5&sort_by=published_at&sort_order=asc"
        )
        assert response.status_code == 200

    def test_get_video_not_found(self, migrated_discovery_client: TestClient) -> None:
        response = migrated_discovery_client.get("/api/v1/videos/99999")
        assert response.status_code == 404

    def test_discovery_run_requires_api_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "database" / "app.db"))
        monkeypatch.setenv("TEMP_DIR", str(tmp_path / "jobs"))
        # No YOUTUBE_API_KEY set.
        alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(alembic_cfg, "head")
        settings = Settings(_env_file=None)
        with TestClient(create_app(settings), raise_server_exceptions=False) as client:
            response = client.post("/api/v1/discovery/run")
            assert response.status_code == 422  # configuration_error

    def test_discovery_run_mocked(self, migrated_discovery_client: TestClient) -> None:
        """Discovery endpoint returns 200 with a run summary when API is mocked."""
        with patch("app.api.videos.DiscoveryService.discover_all_channels") as mock_discover:
            from app.domain.videos import DiscoveryRunSummary

            mock_discover.return_value = DiscoveryRunSummary(channels_checked=0)
            response = migrated_discovery_client.post("/api/v1/discovery/run")
        assert response.status_code == 200
        data = response.json()
        assert "new_videos_added" in data
        assert "channels_checked" in data

    def test_discovery_channel_mocked(self, migrated_discovery_client: TestClient) -> None:
        with patch("app.api.videos.DiscoveryService.discover_one_channel") as mock_discover:
            from app.domain.videos import DiscoveryRunSummary

            mock_discover.return_value = DiscoveryRunSummary(channels_checked=1)
            response = migrated_discovery_client.post("/api/v1/discovery/channel/1")
        assert response.status_code == 200

    def test_list_videos_invalid_sort_rejected(self, migrated_discovery_client: TestClient) -> None:
        response = migrated_discovery_client.get("/api/v1/videos?sort_by=INVALID")
        assert response.status_code == 422

    def test_list_videos_channel_filter(self, migrated_discovery_client: TestClient) -> None:
        response = migrated_discovery_client.get("/api/v1/videos?channel_id=1")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
