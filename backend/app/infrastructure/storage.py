from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryFile

from app.core.config import Settings


@dataclass(frozen=True)
class Storage:
    videos: Path
    frames: Path
    slides: Path
    pdfs: Path
    logs: Path
    database: Path

    @classmethod
    def from_settings(cls, settings: Settings) -> "Storage":
        assert settings.temp_dir is not None
        assert settings.database_path is not None
        assert settings.download_dir is not None
        return cls(
            videos=settings.download_dir,
            frames=settings.frame_dir or settings.temp_dir / "frames",
            slides=settings.temp_dir / "slides",
            pdfs=settings.pdf_dir or settings.storage_dir / "pdfs",
            logs=settings.storage_dir / "logs",
            database=settings.database_path.parent,
        )

    def initialize(self) -> None:
        for directory in (
            self.videos,
            self.frames,
            self.slides,
            self.pdfs,
            self.logs,
            self.database,
        ):
            directory.mkdir(parents=True, exist_ok=True)
            # Probe actual write access; permission bits alone do not account for ACLs.
            with TemporaryFile(dir=directory) as probe:
                probe.write(b"storage-check")
                probe.flush()
