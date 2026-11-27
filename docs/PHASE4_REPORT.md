# Phase 4 Completion Report — Video Acquisition

Date: 2026-11-27

## 1. Implementation summary

Implemented the Phase 4 video acquisition module using the official `yt-dlp` Python integration (`yt_dlp.YoutubeDL`), `FFprobe` media validation, SQLite persistence via SQLAlchemy and Alembic, non-blocking FastAPI endpoints, and download management UI on the Videos page:

- **Download domain contracts** (`backend/app/domain/downloads.py`): defined `DownloadStatus` (`pending`, `downloading`, `downloaded`, `failed`, `cancelled`), `DownloadProgress`, `MediaProbeResult`, `DownloadRequest`, `DownloadResult`, `BulkDownloadSummary`, `VideoDownloaderAdapter`, `MediaProbeValidator`, and specific domain exceptions.
- **yt-dlp acquisition adapter** (`backend/app/infrastructure/ytdlp_downloader.py`): isolated `yt_dlp.YoutubeDL` behind `VideoDownloaderAdapter`, enforcing <=720p video-only streams (`bestvideo[height<=720][acodec=none]...`), disabling audio, subtitles, playlists, thumbnails, and info-json files, sanitizing YouTube IDs against path traversal, supporting `.part` resume (`continuedl=True`), and honoring cancellation events and timeouts in progress hooks.
- **FFprobe media validator** (`backend/app/infrastructure/media_probe.py`): `FFprobeValidator` inspects downloaded files via `subprocess.run` argument arrays and verifies video stream presence, absence of audio streams, `height <= max_resolution`, positive duration, valid codec, and non-zero file size.
- **Database & repository** (`backend/app/infrastructure/models.py`, `backend/app/repositories/videos.py`, `backend/migrations/versions/91dda657a047_add_video_download_columns.py`): extended `videos` with `download_status`, `local_video_path`, `actual_resolution`, `file_size_bytes`, `video_codec`, `download_progress`, `download_started_at`, `download_completed_at`, `download_retry_count`, and `download_error`, keeping `download_status` independent of `processing_status` and preserving download state across repeated discovery.
- **Download service** (`backend/app/services/downloader.py`): `VideoDownloadService` executes downloads asynchronously on a `ThreadPoolExecutor` (`DOWNLOAD_CONCURRENT_LIMIT=1`), prevents concurrent operations on the same video and duplicate downloads, validates available disk space (`DOWNLOAD_MIN_FREE_DISK_MB=500`), performs bounded exponential-backoff retries on transient errors (`DOWNLOAD_RETRY_ATTEMPTS=3`), deletes invalid files when FFprobe validation fails, reconciles stale `downloading` rows on startup, and safely deletes local files inside `DOWNLOAD_DIR`.
- **Backend API** (`backend/app/api/videos.py`): added `POST /api/v1/videos/{id}/download`, `POST /api/v1/videos/downloads/bulk`, `GET /api/v1/videos/{id}/download/progress`, `GET /api/v1/videos/downloads/active`, `POST /api/v1/videos/{id}/download/cancel`, `POST /api/v1/videos/{id}/download/retry`, and `DELETE /api/v1/videos/{id}/download`.
- **Frontend Videos page** (`frontend/src/features/videos/videos-page.tsx`, `frontend/src/services/videos.ts`): added row/bulk selection, individual and bulk download actions, live progress bar with percentage/speed/ETA (polled via TanStack Query only while downloads are active), actual resolution and file size display, cancel/retry buttons, delete confirmation modal, and error display.

## 2. Files created and modified

### Created
- `backend/app/domain/downloads.py`
- `backend/app/infrastructure/media_probe.py`
- `backend/app/infrastructure/ytdlp_downloader.py`
- `backend/app/services/downloader.py`
- `backend/migrations/versions/91dda657a047_add_video_download_columns.py`
- `backend/tests/test_downloader.py`
- `docs/PHASE4_REPORT.md`

### Modified
- `backend/pyproject.toml` and `backend/uv.lock`
- `backend/app/core/config.py`
- `backend/app/core/errors.py`
- `backend/app/domain/videos.py`
- `backend/app/infrastructure/models.py`
- `backend/app/infrastructure/storage.py`
- `backend/app/repositories/videos.py`
- `backend/app/api/videos.py`
- `backend/app/main.py`
- `frontend/src/services/videos.ts`
- `frontend/src/features/videos/videos-page.tsx`
- `frontend/src/features/videos/videos-page.test.tsx`
- `frontend/e2e/videos.spec.ts`
- `docker-compose.yml`
- `.env.example`
- `README.md`
- `ARCHITECTURE.md`
- `PLANS.md`
- `CHANGELOG.md`

## 3. Architectural decisions

- **Official `yt_dlp.YoutubeDL` Python integration**: Isolated in `YtDlpVideoDownloader` behind `VideoDownloaderAdapter` so business logic has zero dependency on `yt-dlp`.
- **Bounded `ThreadPoolExecutor` for non-blocking execution**: Keeps Phase 4 minimal without introducing Phase 8's persistent job queue/scheduler, while preventing API request blocking and enforcing `DOWNLOAD_CONCURRENT_LIMIT=1`.
- **Strict FFprobe post-download gate**: Downloaded files are never marked `downloaded` until `FFprobeValidator` confirms video-only streams within `DOWNLOAD_MAX_RESOLUTION`. Invalid files are deleted and marked `failed`.
- **Separate `download_status` column**: Keeps acquisition state independent of `processing_status` and ensures repeated discovery (`create_or_skip`) never resets download metadata.

## 4. Dependencies added and their justification

- `yt-dlp==2026.11.23`: Official Python library for authorized video-only stream acquisition, progress hooks, and `.part` download resumption.

## 5. Tests executed and actual results

- **Backend Pytest** (`cd backend && uv run pytest`): **125 passed in 2.78s** (`test_channels.py`: 29, `test_discovery.py`: 59, `test_downloader.py`: 17, `test_foundation.py`: 20). External downloads are mocked in unit/API tests; `FFprobeValidator` tests use real synthetic MP4 fixtures generated by `ffmpeg`.
- **Alembic** (`cd backend && uv run alembic check`): exited 0 (`No new upgrade operations detected.`).
- **Frontend Vitest** (`cd frontend && npm test`): **30 passed across 4 test files** (`api.test.ts`: 6, `app.test.tsx`: 5, `channels-page.test.tsx`: 5, `videos-page.test.tsx`: 14).
- **Playwright E2E (local)** (`cd frontend && npm run test:e2e`): **9 passed in 3.8s**.
- **Playwright E2E (Docker)** (`cd frontend && E2E_BASE_URL=http://127.0.0.1:8080 npm run test:e2e`): **9 passed in 1.5s**.
- **Live Docker 720p download, SIGTERM recovery & persistence**:
  - Seeded authorized 720p+ sample `aqz-KE-bpKQ` (Big Buck Bunny 60fps, Creative Commons) and `jNQXAC9IVRw` in Docker backend.
  - Cancelled `jNQXAC9IVRw` (`download_status="cancelled"`, `download_requested=False`).
  - Started `aqz-KE-bpKQ`, observed live progress (`progress_percent=0.4`, `downloaded_bytes=261120`, `total_bytes=71283827`, `speed_bytes_per_sec=4728526.85`, `eta_seconds=15.0`, `is_live=True`) and `aqz-KE-bpKQ.mp4.part` (`1047552` bytes) on disk.
  - Executed `docker compose restart backend` mid-download (`SIGTERM`): backend logged `Preserved interrupted download state for video_id=1`, then on startup logged `Recovered interrupted download for video_id=1 (attempt 1/3)` and `Downloaded and verified video_id=1 (1280x720, av1, 71283827 bytes)`.
  - Independent `ffprobe` check confirmed `[('video', 'av1', 1280, 720)]` (1 video stream, 0 audio streams).
  - Verified `jNQXAC9IVRw` remained `cancelled` (`download_requested=False`) after restart.
  - Verified duplicate download on `aqz-KE-bpKQ` returned `409` and `DELETE /api/v1/videos/1/download` removed the file and reset status to `pending` (`downloaded_bytes=0`).

## 6. Linting and type-checking results

- `cd backend && uv run ruff format --check .`: **passed** (38 files already formatted).
- `cd backend && uv run ruff check .`: **passed** (All checks passed).
- `cd backend && uv run mypy`: **passed** (Success: no issues found in 38 source files).
- `cd frontend && npm run format`: **passed**.
- `cd frontend && npm run lint`: **passed** (`eslint .`, 0 errors/warnings).
- `cd frontend && npm run typecheck`: **passed** (`tsc -b`, 0 errors).
- `cd frontend && npm run build`: **passed** (`tsc -b && vite build`).

## 7. Acceptance criteria status

1. Individual and selected-video downloads work: **Passed**.
2. Video resolution is limited to 720p by default: **Passed**.
3. Audio is excluded: **Passed** (enforced in format selector and verified by FFprobe).
4. Downloaded files pass FFprobe validation: **Passed**.
5. Actual progress is visible in the UI: **Passed** (Vitest + live progress endpoint).
6. Cancellation and retries work: **Passed**.
7. Duplicate downloads are prevented: **Passed**.
8. Temporary storage is managed safely: **Passed** (ID sanitization, path containment, disk space check, safe deletion).
9. Files persist across Docker container recreation: **Passed**.
10. Live acquisition verified using an authorized sample: **Passed** (`jNQXAC9IVRw` in Docker).
11. All tests, linting, type checks and production builds pass: **Passed**.
12. No earlier phase regressions introduced: **Passed**.

## 8. Known issues and limitations

- **In-process executor**: Downloads run in a single-process `ThreadPoolExecutor` (`DOWNLOAD_CONCURRENT_LIMIT=1`). Interrupted downloads are persisted in SQLite and automatically recovered on startup using `.part` files up to `DOWNLOAD_RETRY_ATTEMPTS`; multi-worker/scheduled queue orchestration belongs to Phase 8.
- **YouTube bot/rate-limit challenges**: Live YouTube downloads depend on network/IP reputation and `yt-dlp` extractor compatibility; no authentication cookies or bypasses are used.

## 9. Pending work

- Phase 5: Frame extraction (FFmpeg interval and timestamp-based PNG extraction).
