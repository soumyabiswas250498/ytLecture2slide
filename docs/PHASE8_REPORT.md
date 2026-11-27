# Phase 8 Completion Report — Automated Pipeline, Scheduling and Storage Cleanup

Date: 2026-11-27  
Branch / State: Local workspace (uncommitted; ready for user acceptance)

---

## 1. Implementation Summary

Phase 8 connects all existing processing stages (discovery, eligibility evaluation, video acquisition, frame extraction, slide processing, PDF generation, PDF validation, and intermediate cleanup) into an unattended automated pipeline with persistent daily scheduling, startup recovery, and compact UI controls.

- **Pipeline Orchestrator (`backend/app/services/pipeline.py`)**: Coordinates `DiscoveryService`, `VideoExclusionService`, `VideoDownloadService`, `ExtractionService`, `SlideService`, `PdfService`, and `PipelineCleanupService` without duplicating stage logic. Rechecks video exclusion rules before every stage, reuses valid completed outputs, skips videos with already-valid PDFs unless `reprocess_existing=True`, isolates per-video failures, enforces disk-space thresholds (`min_free_disk_mb`), and supports graceful cancellation, bounded retries, and restart recovery.
- **Persistent Daily Scheduler (`backend/app/services/scheduler.py`)**: Uses APScheduler `BackgroundScheduler` + `SQLAlchemyJobStore` + timezone-aware `CronTrigger` (default `03:00` `Asia/Kolkata`, `coalesce=True`, `max_instances=1`, `misfire_grace_time=3600`). Settings persist in `app_settings` (`pipeline_settings`) and dynamically reschedule the job on update.
- **Validated Intermediate Cleanup (`backend/app/services/pipeline_cleanup.py`)**: Validates the published PDF via PyMuPDF (existence, non-empty, readability, page count, embedded image per page, and `source_slide_generation` match) under `media_lock` before removing managed intermediates (`download_dir`, `frame_dir/<video_id>`, `temp_dir/slides/<video_id>`). Sets explicit `cleaned` status (`DownloadStatus.CLEANED`, `ExtractionStatus.CLEANED`, `SlideState.status="cleaned"`, `videos.intermediates_cleaned=True`) while preserving PDFs, metadata, statistics, and logs.
- **Frontend Integration**: Implemented `ProcessingJobsPage` (`/jobs`), **Automation, Processing & Storage** settings on `SettingsPage` (`/settings`) using shared `Select`, `Switch`, and inputs, and `Process All Stages` in `UnifiedBulkToolbar` (`/videos`), plus `Cleaned` status badges.

---

## 2. Files Created and Modified

### Backend Created
- `backend/app/domain/pipeline.py`
- `backend/app/repositories/pipeline.py`
- `backend/app/services/pipeline.py`
- `backend/app/services/pipeline_cleanup.py`
- `backend/app/services/scheduler.py`
- `backend/app/api/pipeline.py`
- `backend/migrations/versions/b2c3d4e5f6a7_pipeline_runs_and_cleanup.py`
- `backend/tests/test_pipeline.py`

### Backend Modified
- `backend/pyproject.toml`, `backend/uv.lock` (added `apscheduler>=3.10,<4`)
- `backend/app/core/config.py`, `backend/app/core/errors.py`, `backend/app/main.py`
- `backend/app/domain/downloads.py`, `backend/app/domain/extraction.py`, `backend/app/domain/slides.py`, `backend/app/domain/videos.py`
- `backend/app/infrastructure/models.py`
- `backend/app/repositories/settings.py`, `backend/app/repositories/videos.py`
- `backend/app/services/discovery.py`, `backend/app/services/downloader.py`, `backend/app/services/exclusion.py`, `backend/app/services/extraction.py`, `backend/app/services/slides.py`, `backend/app/services/pdfs.py`
- `backend/app/api/settings.py`, `backend/app/api/videos.py`
- `backend/tests/test_foundation.py`, `backend/tests/test_slides.py` (replaced opt-in `PHASE6_REAL_DATA` skip with deterministic 1280×720 full-frame + JPEG 85 readability test)

### Frontend & Config Created/Modified
- `frontend/src/components/ui/switch.tsx`
- `frontend/src/services/pipeline.ts`, `frontend/src/services/settings.ts`, `frontend/src/services/videos.ts`, `frontend/src/services/extractions.ts`, `frontend/src/services/slides.ts`
- `frontend/src/features/jobs/processing-jobs-page.tsx`, `frontend/src/features/jobs/processing-jobs-page.test.tsx`
- `frontend/src/features/settings/settings-page.tsx`, `frontend/src/features/settings/settings-page.test.tsx`
- `frontend/src/features/videos/unified-bulk-toolbar.tsx`, `frontend/src/features/videos/videos-page.tsx`, `frontend/src/features/videos/extraction-controls.tsx`, `frontend/src/features/videos/slide-controls.tsx`
- `frontend/src/app.tsx`, `frontend/src/app.test.tsx`
- `frontend/e2e/pipeline.spec.ts`, `frontend/e2e/foundation.spec.ts`
- `docker-compose.yml`, `.env.example`, `README.md`, `REQUIREMENTS.md`, `ARCHITECTURE.md`, `PLANS.md`, `CHANGELOG.md`

---

## 3. Architectural Decisions

1. **Orchestrator Composition**: `PipelineOrchestrator` delegates to existing stage services (`VideoDownloadService`, `ExtractionService`, `SlideService`, `PdfService`) and awaits their `Future` objects with `timeout=0.5` loops checking `cancel_event`, avoiding busy-waiting and duplicating worker pools.
2. **Explicit `cleaned` State**: Added `"cleaned"` to `DownloadStatus`, `ExtractionStatus`, and `SlideState.status` plus `videos.intermediates_cleaned` and `videos.intermediates_cleaned_at` so intentionally removed intermediates are never misreported as missing or failed, and reprocessing cleanly reacquires the source.
3. **Single-Owner Persistent Scheduler**: APScheduler `BackgroundScheduler` with `SQLAlchemyJobStore` (`apscheduler_jobs` table in SQLite) runs in-process with `coalesce=True`, `max_instances=1`, and `misfire_grace_time=3600`, backed by `PipelineRepository.create_run` active-run conflict checks (`409 Conflict` on overlapping runs).
4. **Non-destructive SQLite Migration**: `b2c3d4e5f6a7` uses `op.add_column` directly on `videos` instead of `batch_alter_table`, avoiding SQLite temporary table (`_alembic_tmp_videos`) collisions.

---

## 4. Automated Test & Quality Results

- **Backend Pytest**: `272 passed, 0 failed, 0 skipped` (`uv run pytest -q`). Includes `tests/test_pipeline.py` (E2E local video to PDF + cleanup, exclusion enforcement, failure isolation, corrupt PDF preserving intermediates, overlap 409 + cancellation, disk-space safeguard, scheduler timezone & persistence, restart recovery) and updated `tests/test_slides.py` full-frame + JPEG 85 readability test.
- **Backend Lint & Types**: `uv run ruff check .` (0 errors), `uv run mypy app migrations tests scripts` (`Success: no issues found in 87 source files`).
- **Alembic**: `uv run alembic upgrade head` (`b2c3d4e5f6a7 (head)`) and `uv run alembic check` (`No new upgrade operations detected.`).
- **Frontend Unit Tests**: `13` Vitest files, `61 passed` (`npm test`).
- **Frontend Quality & Build**: `npm run format:check`, `npm run lint` (0 errors, 0 warnings), `npm run typecheck` (`tsc -b`), `npm run build` (`vite build`) all passed.
- **Playwright E2E**: `15 passed` locally (`npm run test:e2e`) and `15 passed` against Docker Compose (`E2E_BASE_URL=http://127.0.0.1:8080 npm run test:e2e`).

---

## 5. Real-World Docker Verification

- **Live YouTube Discovery (`POST /api/v1/discovery/run`)**: Checked 3 active channels (`VSCE Academy`, `TWS Academy`, `BSSEI Competitive`), found 31 videos, skipped 21 existing, rejected 7 by duration (`<= 1200s`), deferred 3 livestreams, `api_requests_made=6`, `search_requests_made=3`, `duration_seconds=1.38s`, `errors=[]`.
- **Pipeline Execution & Cleanup (`Run #2`, `video_id=1`, `vqYNwaqFPJM`)**:
  - Reused existing valid outputs, validated the published 77-page PDF (`92,008,735` bytes, `GET /api/v1/pdfs/1/download` -> HTTP 200), and executed intermediate cleanup in `1.05s`.
  - **Cleanup Result**: Removed `1,404` intermediate files (`3,084,433,324` bytes / ~2.87 GiB reclaimed); `/data` volume usage dropped from `4.6G` to `1.7G`.
- **Scheduled Trigger Verification**: Temporarily set `scheduler_time` to `15:21` `Asia/Kolkata` via `PUT /api/v1/settings/pipeline`; APScheduler automatically triggered `Run #3` (`trigger_type="scheduled"`) at `2026-11-27T09:51:00.009401Z` (`15:21:00 IST`). Restored `03:00` `Asia/Kolkata` (`next_run_at="2026-11-27T21:30:00Z"`).
- **Container Recreation Persistence**: Verified `scheduler`, `runs` (`total=3`), and `pdfs` (`total=1`) survive `docker compose up -d --force-recreate --wait`.

---

## 6. Known Issues & Limitations

- **Unauthenticated YouTube `yt-dlp` Rate-Limiting / Bot Check**: During Docker `Run #1` (`video_ids=[1, 15, 2, 19, 3]`), `video_id=1` was skipped (valid PDF existed), `video_id=15` was excluded (`Math`), and `video_id=2` / `video_id=19` failed acquisition with `"Video unavailable or access restricted. Confirm permission and availability."` while per-video failure isolation continued cleanly to subsequent videos. Live YouTube acquisition inside Docker remains subject to YouTube's IP/authentication policies when no cookies/authorized session are supplied.
- **Phase 9 Deferred**: Dashboard summary consolidation remains scoped for Phase 9.
