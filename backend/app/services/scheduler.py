"""Persistent APScheduler service for automated daily pipeline execution."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore  # type: ignore[import-untyped]
from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from sqlalchemy import Engine

from app.domain.pipeline import PipelineConflictError, PipelineSettings, SchedulerStatus
from app.repositories.pipeline import PipelineRepository
from app.services.pipeline import PipelineOrchestrator

logger = logging.getLogger("app.services.scheduler")

DAILY_JOB_ID = "daily_pipeline_run"

_orchestrator_ref: PipelineOrchestrator | None = None


def _execute_scheduled_pipeline() -> None:
    """Module-level callable required by APScheduler SQLAlchemyJobStore serialization."""
    if _orchestrator_ref is None:
        logger.warning("Scheduled pipeline triggered before orchestrator initialization.")
        return
    try:
        _orchestrator_ref.trigger_run("scheduled")
    except PipelineConflictError as exc:
        logger.info("Skipping overlapping scheduled pipeline run: %s", exc)
    except Exception:
        logger.exception("Scheduled pipeline execution failed to start.")


class PipelineSchedulerService:
    """Single-owner persistent scheduler backed by APScheduler + SQLite."""

    def __init__(
        self,
        *,
        engine: Engine,
        orchestrator: PipelineOrchestrator,
        pipeline_repo: PipelineRepository,
        misfire_grace_seconds: int = 3600,
        start_scheduler: bool = True,
    ) -> None:
        global _orchestrator_ref
        _orchestrator_ref = orchestrator
        self._orchestrator = orchestrator
        self._repo = pipeline_repo
        self._misfire_grace_seconds = misfire_grace_seconds

        jobstores = {"default": SQLAlchemyJobStore(engine=engine)}
        self._scheduler = BackgroundScheduler(
            jobstores=jobstores,
            timezone=ZoneInfo("UTC"),
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": misfire_grace_seconds,
            },
        )
        if start_scheduler:
            self._scheduler.start()
            self.sync_schedule(self._orchestrator.get_pipeline_settings())

    def sync_schedule(self, settings: PipelineSettings) -> None:
        if not settings.scheduler_enabled:
            if self._scheduler.get_job(DAILY_JOB_ID) is not None:
                self._scheduler.remove_job(DAILY_JOB_ID)
            logger.info("Automatic daily scheduling is disabled.")
            return

        hour_str, minute_str = settings.scheduler_time.split(":")
        tz = ZoneInfo(settings.timezone)
        trigger = CronTrigger(hour=int(hour_str), minute=int(minute_str), timezone=tz)
        self._scheduler.add_job(
            _execute_scheduled_pipeline,
            trigger=trigger,
            id=DAILY_JOB_ID,
            name="Daily Lecture Pipeline",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=self._misfire_grace_seconds,
        )
        job = self._scheduler.get_job(DAILY_JOB_ID)
        next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
        logger.info(
            "Scheduled daily pipeline at %s (%s), next_run_at=%s",
            settings.scheduler_time,
            settings.timezone,
            next_run,
        )

    def get_status(self) -> SchedulerStatus:
        settings = self._orchestrator.get_pipeline_settings()
        job = self._scheduler.get_job(DAILY_JOB_ID) if settings.scheduler_enabled else None
        next_run_at: datetime | None = None
        if job is not None and job.next_run_time is not None:
            next_run_at = job.next_run_time.astimezone(UTC)
        latest_scheduled = self._repo.get_latest_scheduled_run()
        active = self._repo.get_active_run()
        return SchedulerStatus(
            enabled=settings.scheduler_enabled,
            frequency=settings.scheduler_frequency,
            time=settings.scheduler_time,
            timezone=settings.timezone,
            next_run_at=next_run_at,
            last_run_at=latest_scheduled.started_at if latest_scheduled else None,
            is_running=active is not None,
        )

    def shutdown(self) -> None:
        global _orchestrator_ref
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        _orchestrator_ref = None
