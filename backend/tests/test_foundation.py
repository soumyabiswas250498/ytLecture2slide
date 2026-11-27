import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.core.logging import JsonFormatter
from app.infrastructure.storage import Storage
from app.main import create_app


def test_factory_initializes_and_closes_database(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}
        with app.state.sessions() as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1
    assert settings.database_path is not None
    assert settings.database_path.is_file()


@pytest.mark.parametrize("endpoint,status", [("health", "ok"), ("ready", "ready")])
def test_health(client: TestClient, endpoint: str, status: str) -> None:
    response = client.get(f"/api/v1/{endpoint}")
    assert response.status_code == 200
    assert response.json() == {"status": status}


def test_not_ready_does_not_leak_database_details(client: TestClient) -> None:
    with patch(
        "app.api.health.check_database",
        side_effect=OperationalError("secret SQL", {}, RuntimeError("private path")),
    ):
        response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "not_ready"
    assert "private" not in response.text
    assert client.get("/api/v1/health").status_code == 200


def test_missing_route_has_consistent_error(client: TestClient) -> None:
    response = client.get("/api/v1/missing")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "http_error", "message": "Not Found"}}


def test_errors_are_sanitized(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/failure")
    def failure() -> None:
        raise RuntimeError("sensitive internal detail")

    @app.get("/validate")
    def validate(count: int) -> dict[str, int]:
        return {"count": count}

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/failure")
        assert response.status_code == 500
        assert "sensitive" not in response.text
        invalid = client.get("/validate", params={"count": "secret"})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "validation_error"
        assert "secret" not in invalid.text


@pytest.mark.parametrize(
    "values",
    [
        {"backend_port": 0},
        {"backend_port": 65536},
        {"app_env": "unknown"},
        {"timezone": "Invalid/Zone"},
        {"log_level": "VERBOSE"},
        {"cors_origins": ["*"]},
        {"cors_origins": ["https://example.org/path"]},
    ],
)
def test_invalid_config_is_rejected(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_environment_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEND_PORT", "8123")
    monkeypatch.setenv("CORS_ORIGINS", '["https://lectures.example.org"]')
    settings = Settings(_env_file=None)
    assert settings.backend_port == 8123
    assert settings.cors_origins == ["https://lectures.example.org"]
    assert settings.database_path == tmp_path / "database" / "app.db"


def test_storage_is_idempotent_and_preserves_content(settings: Settings) -> None:
    storage = Storage.from_settings(settings)
    storage.initialize()
    artifact = storage.pdfs / "existing.pdf"
    artifact.write_bytes(b"preserve-me")
    storage.initialize()
    assert artifact.read_bytes() == b"preserve-me"
    assert all(
        path.is_dir()
        for path in (
            storage.videos,
            storage.frames,
            storage.slides,
            storage.pdfs,
            storage.logs,
            storage.database,
        )
    )


def test_storage_failure_stops_startup(settings: Settings) -> None:
    storage = Storage.from_settings(settings)
    storage.videos.parent.mkdir(parents=True)
    storage.videos.write_text("not a directory")
    with pytest.raises(FileExistsError), TestClient(create_app(settings)):
        pass


def test_cors_allows_only_configured_origins(client: TestClient) -> None:
    allowed = client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    denied = client.get("/api/v1/health", headers={"Origin": "https://untrusted.example"})
    assert "access-control-allow-origin" not in denied.headers


def test_database_survives_application_recreation(settings: Settings) -> None:
    for iteration in range(2):
        app: FastAPI = create_app(settings)
        with TestClient(app), app.state.engine.begin() as connection:
            if iteration == 0:
                connection.execute(text("CREATE TABLE persistence_probe (value TEXT)"))
                connection.execute(text("INSERT INTO persistence_probe VALUES ('retained')"))
            assert (
                connection.execute(text("SELECT value FROM persistence_probe")).scalar_one()
                == "retained"
            )


def test_migration_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "migration.db"))
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    command.check(config)
    app = create_app(Settings())
    with TestClient(app):
        assert set(inspect(app.state.engine).get_table_names()) == {
            "alembic_version",
            "channels",
            "videos",
            "extractions",
            "slide_processing",
            "channel_board_profiles",
        }


def test_structured_log_includes_job_context() -> None:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "ready", (), None)
    record.job_id = "example-job"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["job_id"] == "example-job"
    assert payload["message"] == "ready"
    assert payload["level"] == "INFO"
