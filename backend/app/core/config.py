from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.pdfs import PdfConfig
from app.domain.slides import SlideConfig

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    backend_host: str = Field(default="127.0.0.1", min_length=1)
    backend_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    storage_dir: Path = PROJECT_ROOT / "storage"
    temp_dir: Path | None = None
    database_path: Path | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    timezone: str = "Asia/Kolkata"
    default_search_keyword: str = Field(default="IDO", min_length=1, max_length=120)
    youtube_api_key: str | None = Field(default=None)
    discovery_lookback_days: int = Field(default=7, ge=1, le=30)
    discovery_min_duration_seconds: int = Field(default=1200, ge=1)  # strictly > 1200s (20 min)
    discovery_max_results_per_channel: int = Field(default=50, ge=1, le=200)
    discovery_quota_limit: int = Field(default=10000, ge=1)
    discovery_search_quota_limit: int = Field(default=100, ge=1)
    download_max_resolution: int = Field(default=720, ge=144, le=2160)
    download_audio_enabled: bool = False
    download_concurrent_limit: int = Field(default=1, ge=1, le=5)
    download_retry_attempts: int = Field(default=3, ge=0, le=10)
    download_connect_timeout_seconds: int = Field(default=30, ge=5, le=300)
    download_inactivity_timeout_seconds: int = Field(default=120, ge=10, le=1800)
    download_max_total_timeout_seconds: int | None = Field(default=None, ge=30, le=86400)
    download_min_free_disk_mb: int = Field(default=500, ge=50)
    download_dir: Path | None = None
    frame_dir: Path | None = None
    cleanup_retention_hours: float = Field(default=48, gt=0, allow_inf_nan=False)
    cleanup_dry_run: bool = False
    download_js_runtime: Literal["deno", "node", "quickjs"] = "deno"
    download_js_runtime_path: str | None = None
    extraction_interval_seconds: float = Field(default=60, ge=0.001, allow_inf_nan=False)
    extraction_concurrent_limit: int = Field(default=1, ge=1, le=5)
    extraction_retry_attempts: int = Field(default=3, ge=0, le=10)
    extraction_min_free_disk_mb: int = Field(default=500, ge=0)
    extraction_max_filter_bytes: int = Field(default=32000, ge=1024, le=65536)
    extraction_max_frames: int = Field(default=100000, ge=1)
    extraction_strategy: Literal["seek", "sequential"] = "seek"
    extraction_threads: int = Field(default=1, ge=1, le=16)
    extraction_progress_interval_seconds: float = Field(default=2, ge=0.1)

    slide_processing: SlideConfig = Field(default_factory=SlideConfig)
    slide_channel_profiles: dict[str, SlideConfig] = Field(default_factory=dict)
    slide_concurrent_limit: int = Field(default=1, ge=1, le=3)
    slide_retry_attempts: int = Field(default=3, ge=0, le=10)

    pdf_dir: Path | None = None
    pdf_concurrent_limit: int = Field(default=1, ge=1, le=3)
    pdf_retry_attempts: int = Field(default=3, ge=0, le=10)
    pdf_min_free_disk_mb: int = Field(default=500, ge=0)
    pdf_zip_max_files: int = Field(default=100, ge=1, le=1000)
    pdf_zip_max_total_bytes: int = Field(default=2 * 1024 * 1024 * 1024, ge=1024 * 1024)
    pdf_generation: PdfConfig = Field(default_factory=PdfConfig)

    def __repr__(self) -> str:
        """Mask youtube_api_key to prevent accidental log exposure."""
        masked = "***" if self.youtube_api_key else None
        return (
            f"Settings(app_env={self.app_env!r}, "
            f"youtube_api_key={masked!r}, "
            f"database_path={self.database_path!r})"
        )

    @field_validator("download_max_total_timeout_seconds", mode="before")
    @classmethod
    def empty_timeout_to_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("default_search_keyword")
    @classmethod
    def valid_default_keyword(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("default_search_keyword must not be empty")
        return cleaned

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("cors_origins")
    @classmethod
    def valid_origins(cls, origins: list[str]) -> list[str]:
        from urllib.parse import urlsplit

        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins without paths")
        return origins

    @model_validator(mode="after")
    def resolve_paths(self) -> "Settings":
        self.storage_dir = self.absolute(self.storage_dir)
        self.temp_dir = self.absolute(self.temp_dir or self.storage_dir / "jobs")
        self.database_path = self.absolute(
            self.database_path or self.storage_dir / "database" / "app.db"
        )
        self.download_dir = self.absolute(self.download_dir or self.temp_dir / "videos")
        self.frame_dir = self.absolute(self.frame_dir or self.temp_dir / "frames")
        self.pdf_dir = self.absolute(self.pdf_dir or self.storage_dir / "pdfs")
        return self

    @staticmethod
    def absolute(path: Path) -> Path:
        return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()
