import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.channels import router as channels_router
from app.api.extractions import router as extraction_router
from app.api.health import router as health_router
from app.api.pdfs import router as pdfs_router
from app.api.settings import router as settings_router
from app.api.slides import router as slides_router
from app.api.videos import discovery_router, videos_router
from app.core.config import Settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.infrastructure.database import check_database, create_database_engine, session_factory
from app.infrastructure.frame_extractor import FFmpegFrameExtractor
from app.infrastructure.media_probe import FFprobeValidator
from app.infrastructure.pdf_generator import PyMuPdfGenerator
from app.infrastructure.storage import Storage
from app.infrastructure.ytdlp_downloader import YtDlpVideoDownloader
from app.repositories.channels import ChannelRepository
from app.repositories.extractions import ExtractionRepository
from app.repositories.pdfs import PdfRepository
from app.repositories.settings import SettingsRepository
from app.repositories.slides import ChannelBoardProfileRepository, SlideRepository
from app.repositories.videos import VideoRepository
from app.services.downloader import VideoDownloadService
from app.services.exclusion import VideoExclusionService
from app.services.extraction import ExtractionService
from app.services.imaging.pipeline import SlideProcessor
from app.services.pdfs import PdfService
from app.services.slides import SlideService


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        storage = Storage.from_settings(config)
        storage.initialize()
        configure_logging(config.log_level, storage.logs)
        assert config.database_path is not None
        engine = create_database_engine(config.database_path)
        try:
            check_database(engine)
            sessions = session_factory(engine)
            app.state.engine = engine
            app.state.sessions = sessions
            app.state.storage = storage
            media_lock = threading.RLock()
            exclusion_service = VideoExclusionService(
                settings_repo=SettingsRepository(sessions),
                video_repo=VideoRepository(sessions),
                lock=media_lock,
            )
            app.state.exclusion_service = exclusion_service
            extraction_service = ExtractionService(
                videos=VideoRepository(sessions),
                repository=ExtractionRepository(sessions),
                settings=config,
                media_lock=media_lock,
                extractor=FFmpegFrameExtractor(
                    min_free_disk_mb=config.extraction_min_free_disk_mb,
                    threads=config.extraction_threads,
                    strategy=config.extraction_strategy,
                    max_frames=config.extraction_max_frames,
                    max_filter_bytes=config.extraction_max_filter_bytes,
                ),
            )
            app.state.extraction_service = extraction_service
            extraction_service.cleanup_service.cleanup(dry_run=config.cleanup_dry_run)
            extraction_service.recover()
            slide_service = SlideService(
                videos=VideoRepository(sessions),
                repository=SlideRepository(sessions),
                board_profiles=ChannelBoardProfileRepository(sessions),
                extraction=extraction_service,
                settings=config,
                media_lock=media_lock,
                processor=SlideProcessor(
                    FFmpegFrameExtractor(
                        min_free_disk_mb=config.extraction_min_free_disk_mb,
                        threads=config.extraction_threads,
                    )
                ),
            )
            app.state.slide_service = slide_service
            extraction_service.processing_guard = slide_service.assert_inactive
            extraction_service.delete_guard = slide_service.assert_no_published_slides
            slide_service.recover()

            pdf_service = PdfService(
                videos=VideoRepository(sessions),
                channels=ChannelRepository(sessions),
                repository=PdfRepository(sessions),
                slides=slide_service,
                generator=PyMuPdfGenerator(),
                settings=config,
                media_lock=media_lock,
                settings_repo=SettingsRepository(sessions),
            )
            app.state.pdf_service = pdf_service
            slide_service.pdf_guard = pdf_service.assert_inactive
            pdf_service.recover()

            def media_guard(video_id: int) -> None:
                extraction_service.assert_inactive(video_id)
                slide_service.assert_inactive(video_id)

            download_service = VideoDownloadService(
                media_lock=media_lock,
                extraction_guard=media_guard,
                video_repo=VideoRepository(sessions),
                downloader=YtDlpVideoDownloader(
                    config.download_js_runtime, config.download_js_runtime_path
                ),
                validator=FFprobeValidator(),
                settings=config,
            )
            download_service.recover_interrupted_downloads()
            app.state.download_service = download_service
            logging.getLogger("app").info("Application started")
            yield
        finally:
            if hasattr(app.state, "pdf_service"):
                app.state.pdf_service.shutdown()
            if hasattr(app.state, "slide_service"):
                app.state.slide_service.shutdown()
            if hasattr(app.state, "extraction_service"):
                app.state.extraction_service.shutdown()
            if hasattr(app.state, "download_service"):
                app.state.download_service.shutdown()
            engine.dispose()
            logging.getLogger("app").info("Database connections closed")

    app = FastAPI(title="ytLecture2slide", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    register_error_handlers(app)
    app.include_router(pdfs_router)
    app.include_router(slides_router)
    app.include_router(extraction_router)
    app.include_router(health_router)
    app.include_router(settings_router)
    app.include_router(channels_router)
    app.include_router(videos_router)
    app.include_router(discovery_router)
    return app
