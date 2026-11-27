import csv
import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.channels import (
    ChannelValidationError,
    normalize_channel_url,
    normalize_sample_video_url,
)
from app.main import create_app


@pytest.mark.parametrize(
    ("raw", "expected_url", "expected_id"),
    [
        (
            "https://www.youtube.com/@WBPSC_Guide/videos?si=tracking123",
            "https://www.youtube.com/@wbpsc_guide",
            None,
        ),
        (
            "http://m.youtube.com/@ScienceHub/?utm_source=share",
            "https://www.youtube.com/@sciencehub",
            None,
        ),
        (
            "https://youtube.com/channel/UC1234567890abcdefghijkl/streams?feature=shared",
            "https://www.youtube.com/channel/UC1234567890abcdefghijkl",
            "UC1234567890abcdefghijkl",
        ),
        (
            "https://www.youtube.com/c/HistoryClass/featured",
            "https://www.youtube.com/c/historyclass",
            None,
        ),
        (
            "https://www.youtube.com/user/LegacyEducator/",
            "https://www.youtube.com/user/legacyeducator",
            None,
        ),
    ],
)
def test_channel_url_normalization(raw: str, expected_url: str, expected_id: str | None) -> None:
    url, yt_id = normalize_channel_url(raw)
    assert url == expected_url
    assert yt_id == expected_id


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not-a-url",
        "ftp://www.youtube.com/@channel",
        "https://vimeo.com/123456",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/channel/INVALID_ID",
        "https://www.youtube.com/@a",
        "https://user:pass@www.youtube.com/@channel",
    ],
)
def test_invalid_channel_urls_rejected(raw: str) -> None:
    with pytest.raises(ChannelValidationError):
        normalize_channel_url(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("   ", None),
        (
            "https://youtu.be/dQw4w9WgXcQ?si=abc&t=42",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        (
            "http://m.youtube.com/watch?v=abc123XYZ90&feature=youtu.be",
            "https://www.youtube.com/watch?v=abc123XYZ90",
        ),
        (
            "https://www.youtube.com/live/liveVid1234?si=xyz",
            "https://www.youtube.com/watch?v=liveVid1234",
        ),
        (
            "https://www.youtube.com/shorts/shortVid123",
            "https://www.youtube.com/watch?v=shortVid123",
        ),
    ],
)
def test_sample_video_url_normalization(raw: str | None, expected: str | None) -> None:
    assert normalize_sample_video_url(raw) == expected


def test_invalid_sample_video_url_rejected() -> None:
    with pytest.raises(ChannelValidationError):
        normalize_sample_video_url("https://example.com/video.mp4")


def test_channel_crud_and_persistence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "database" / "app.db"))
    monkeypatch.setenv("TEMP_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("DEFAULT_SEARCH_KEYWORD", "SSC")

    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    created_id: int
    with TestClient(create_app(Settings(_env_file=None))) as client:
        create_res = client.post(
            "/api/v1/channels",
            json={
                "name": "  বাংলা পাঠশালা  ",
                "channel_url": "https://m.youtube.com/@BanglaPathshala/videos?si=123",
                "sample_video_url": "https://youtu.be/vid12345678?t=10",
            },
        )
        assert create_res.status_code == 201
        created = create_res.json()
        created_id = created["id"]
        assert created["name"] == "বাংলা পাঠশালা"
        assert created["channel_url"] == "https://www.youtube.com/@banglapathshala"
        assert created["sample_video_url"] == "https://www.youtube.com/watch?v=vid12345678"
        assert created["search_keyword"] == "SSC"
        assert created["is_active"] is True
        assert created["youtube_channel_id"] is None

        get_res = client.get(f"/api/v1/channels/{created_id}")
        assert get_res.status_code == 200
        assert get_res.json()["name"] == "বাংলা পাঠশালা"

        patch_res = client.patch(
            f"/api/v1/channels/{created_id}",
            json={
                "search_keyword": "WBPSC",
                "sample_video_url": None,
                "is_active": False,
            },
        )
        assert patch_res.status_code == 200
        updated = patch_res.json()
        assert updated["search_keyword"] == "WBPSC"
        assert updated["sample_video_url"] is None
        assert updated["is_active"] is False

    # Recreate app and confirm SQLite persistence
    with TestClient(create_app(Settings(_env_file=None))) as client:
        persisted = client.get(f"/api/v1/channels/{created_id}")
        assert persisted.status_code == 200
        assert persisted.json()["name"] == "বাংলা পাঠশালা"
        assert persisted.json()["is_active"] is False

        del_res = client.delete(f"/api/v1/channels/{created_id}")
        assert del_res.status_code == 204
        assert client.get(f"/api/v1/channels/{created_id}").status_code == 404


def test_duplicate_prevention_by_url_and_youtube_channel_id(
    migrated_client: TestClient,
) -> None:
    res1 = migrated_client.post(
        "/api/v1/channels",
        json={
            "name": "Channel One",
            "channel_url": "https://www.youtube.com/@ChannelOne",
            "youtube_channel_id": "UC1111111111111111111111",
        },
    )
    assert res1.status_code == 201

    # Same URL via mobile host and tracking param
    dup_url = migrated_client.post(
        "/api/v1/channels",
        json={
            "name": "Channel One Copy",
            "channel_url": "http://m.youtube.com/@channelone/videos?si=abc",
        },
    )
    assert dup_url.status_code == 409
    assert dup_url.json()["error"]["code"] == "duplicate_channel"

    # Different URL but matching UC... channel ID extracted from /channel/UC...
    dup_yt_id = migrated_client.post(
        "/api/v1/channels",
        json={
            "name": "Channel One By ID",
            "channel_url": "https://www.youtube.com/channel/UC1111111111111111111111",
        },
    )
    assert dup_yt_id.status_code == 409
    assert dup_yt_id.json()["error"]["code"] == "duplicate_channel"

    # Create second channel and attempt updating it to conflict with first
    res2 = migrated_client.post(
        "/api/v1/channels",
        json={
            "name": "Channel Two",
            "channel_url": "https://www.youtube.com/@ChannelTwo",
        },
    )
    assert res2.status_code == 201
    second_id = res2.json()["id"]

    conflict_patch = migrated_client.patch(
        f"/api/v1/channels/{second_id}",
        json={"channel_url": "https://www.youtube.com/@channelone"},
    )
    assert conflict_patch.status_code == 409


def test_list_search_filter_and_pagination(migrated_client: TestClient) -> None:
    channels = [
        {
            "name": "Alpha History",
            "channel_url": "https://www.youtube.com/@alphahistory",
            "search_keyword": "IDO",
            "is_active": True,
        },
        {
            "name": "Beta Math 100%",
            "channel_url": "https://www.youtube.com/@betamath",
            "search_keyword": "SSC",
            "is_active": False,
        },
        {
            "name": "Gamma Science",
            "channel_url": "https://www.youtube.com/@gammascience",
            "search_keyword": "IDO",
            "is_active": True,
        },
    ]
    for item in channels:
        assert migrated_client.post("/api/v1/channels", json=item).status_code == 201

    page1 = migrated_client.get("/api/v1/channels", params={"page": 1, "page_size": 2})
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["total"] == 3
    assert body1["total_pages"] == 2
    assert len(body1["items"]) == 2
    assert body1["summary"] == {"total": 3, "active": 2, "inactive": 1}

    page2 = migrated_client.get("/api/v1/channels", params={"page": 2, "page_size": 2})
    assert len(page2.json()["items"]) == 1

    # Search by keyword and filter by active status
    ido_active = migrated_client.get(
        "/api/v1/channels", params={"search": "ido", "is_active": "true"}
    )
    assert ido_active.status_code == 200
    assert ido_active.json()["total"] == 2
    # Summary still reflects full registry counts
    assert ido_active.json()["summary"] == {"total": 3, "active": 2, "inactive": 1}

    # Literal '%' search should match only Beta Math 100%, not everything
    percent_search = migrated_client.get("/api/v1/channels", params={"search": "100%"})
    assert percent_search.status_code == 200
    assert percent_search.json()["total"] == 1
    assert percent_search.json()["items"][0]["name"] == "Beta Math 100%"


def test_csv_import_validation_duplicates_and_bengali(migrated_client: TestClient) -> None:
    seed_res = migrated_client.post(
        "/api/v1/channels",
        json={
            "name": "Existing Channel",
            "channel_url": "https://www.youtube.com/@existingchannel",
            "search_keyword": "CUSTOM",
            "is_active": False,
        },
    )
    assert seed_res.status_code == 201

    csv_text = (
        "\ufeffchannel_name,channel_url,sample_video_url,search_keyword,is_active\n"
        "বিজ্ঞান একাডেমি,https://youtube.com/@BigganAcademy/videos?si=99,https://youtu.be/abc123def45?t=5,IDO,true\n"
        "Existing Duplicate,https://m.youtube.com/@existingchannel/featured,,NEW_KW,true\n"
        "In-CSV Duplicate,https://www.youtube.com/@bigganacademy,,,\n"
        "Missing URL Row,,https://youtu.be/abc123def45,,\n"
        ",https://www.youtube.com/@missingname,,,\n"
        "Bad URL Row,https://vimeo.com/12345,,,\n"
        "Valid Inactive,https://www.youtube.com/channel/UC9999999999999999999999,,WBCS,false\n"
    )
    res = migrated_client.post(
        "/api/v1/channels/import",
        files={"file": ("channels.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert res.status_code == 200
    report = res.json()
    assert report["total_rows"] == 7
    assert report["imported_count"] == 2
    assert report["skipped_count"] == 2
    assert report["invalid_count"] == 3

    imported_names = [item["name"] for item in report["imported"]]
    assert imported_names == ["বিজ্ঞান একাডেমি", "Valid Inactive"]
    assert report["imported"][1]["youtube_channel_id"] == "UC9999999999999999999999"
    assert report["imported"][1]["is_active"] is False

    # Existing record was NOT overwritten
    existing_after = migrated_client.get(f"/api/v1/channels/{seed_res.json()['id']}").json()
    assert existing_after["name"] == "Existing Channel"
    assert existing_after["search_keyword"] == "CUSTOM"
    assert existing_after["is_active"] is False

    # Missing URL row is reported clearly without inventing a URL
    error_reasons = {err["row_number"]: err["reason"] for err in report["errors"]}
    assert "missing" in error_reasons[5].lower()
    assert "Channel name is required" in error_reasons[6]


def test_csv_legacy_3_column_and_invalid_header(migrated_client: TestClient) -> None:
    legacy_csv = (
        "channel_name,channel_url,sample_video_url\n"
        "Legacy Channel,https://www.youtube.com/@legacyone,https://www.youtube.com/watch?v=xyz123abc45\n"
    )
    res = migrated_client.post(
        "/api/v1/channels/import",
        files={"file": ("legacy.csv", legacy_csv.encode("utf-8"), "text/csv")},
    )
    assert res.status_code == 200
    assert res.json()["imported_count"] == 1
    assert res.json()["imported"][0]["search_keyword"] == "IDO"

    bad_header_csv = "name,url\nFoo,https://www.youtube.com/@foo\n"
    bad_res = migrated_client.post(
        "/api/v1/channels/import",
        files={"file": ("bad.csv", bad_header_csv.encode("utf-8"), "text/csv")},
    )
    assert bad_res.status_code == 422
    assert bad_res.json()["error"]["code"] == "invalid_csv"


def test_csv_export_template_and_round_trip(
    migrated_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tpl = migrated_client.get("/api/v1/channels/template")
    assert tpl.status_code == 200
    assert "text/csv" in tpl.headers["content-type"]
    assert tpl.text.strip() == "channel_name,channel_url,sample_video_url,search_keyword,is_active"

    # Seed channels including Bengali name and inactive state
    migrated_client.post(
        "/api/v1/channels",
        json={
            "name": "ইতিহাস ক্লাস",
            "channel_url": "https://www.youtube.com/@itihasclass",
            "sample_video_url": "https://youtu.be/hist1234567",
            "search_keyword": "WBPSC",
            "is_active": True,
        },
    )
    migrated_client.post(
        "/api/v1/channels",
        json={
            "name": "Paused Channel",
            "channel_url": "https://www.youtube.com/@pausedchannel",
            "search_keyword": "IDO",
            "is_active": False,
        },
    )

    exported = migrated_client.get("/api/v1/channels/export")
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert len(rows) == 2
    assert rows[0]["channel_name"] == "ইতিহাস ক্লাস"
    assert rows[0]["sample_video_url"] == "https://www.youtube.com/watch?v=hist1234567"
    assert rows[1]["is_active"] == "false"

    # Re-importing into same DB skips all duplicates
    reimport_same = migrated_client.post(
        "/api/v1/channels/import",
        files={"file": ("export.csv", exported.content, "text/csv")},
    )
    assert reimport_same.status_code == 200
    assert reimport_same.json()["imported_count"] == 0
    assert reimport_same.json()["skipped_count"] == 2

    # Import exported CSV into a fresh DB -> full round-trip
    fresh_dir = tmp_path / "fresh"
    monkeypatch.setenv("STORAGE_DIR", str(fresh_dir))
    monkeypatch.setenv("DATABASE_PATH", str(fresh_dir / "database" / "app.db"))
    monkeypatch.setenv("TEMP_DIR", str(fresh_dir / "jobs"))
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    with TestClient(create_app(Settings(_env_file=None))) as fresh_client:
        round_trip = fresh_client.post(
            "/api/v1/channels/import",
            files={"file": ("export.csv", exported.content, "text/csv")},
        )
        assert round_trip.status_code == 200
        assert round_trip.json()["imported_count"] == 2
        listed = fresh_client.get("/api/v1/channels").json()
        assert listed["summary"] == {"total": 2, "active": 1, "inactive": 1}
        names = {item["name"] for item in listed["items"]}
        assert names == {"ইতিহাস ক্লাস", "Paused Channel"}


def test_validation_error_messages_are_meaningful_and_sanitized(
    migrated_client: TestClient,
) -> None:
    res = migrated_client.post(
        "/api/v1/channels",
        json={"name": "Test", "channel_url": "https://notyoutube.example/secret-token"},
    )
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "validation_error"
    assert "youtube" in body["error"]["message"].lower()
    assert "secret-token" not in res.text
