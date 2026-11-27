# Changelog

Record actual changes to ytLecture2slide here. Maintain a chronological development history. Do not record proposed work as implemented or claim tests that were not executed.

## [Unreleased]

### Changed — Phase 7 Compact Table Details Popover (2026-11-27)

- **Reusable `Popover` & `DetailsPopover` Components**: Added `@radix-ui/react-popover` and shadcn/ui `Popover` (`frontend/src/components/ui/popover.tsx`, `Portal`-rendered with viewport collision handling) plus `DetailsPopover` (`frontend/src/components/shared/details-popover.tsx`) featuring a 32 × 32 px icon-only info trigger, `"View details"` tooltip, outside-click/Escape dismissal, keyboard navigation, and compact key-value + warning layout that never alters table row height.
- **Compact Pipeline Columns**: Replaced the inline `Details`/`Hide details` toggle in `SlideControls` (`frontend/src/features/videos/slide-controls.tsx`) with `DetailsPopover` (showing only status, output slide count, and single-row icon actions) and applied `DetailsPopover` consistently across Download (`frontend/src/features/videos/videos-page.tsx`), Frames (`frontend/src/features/videos/extraction-controls.tsx`), Slides, and PDF (`frontend/src/features/videos/pdf-controls.tsx`) columns.

### Changed — Pre-Phase 8 UI & PDF Compression Refinements (2026-11-27)

- **Compact Icon-Only Table Actions**: Added `size="icon"` (`h-8 w-8`, 32 × 32 px) to `Button` (`frontend/src/components/ui/button.tsx`) and replaced text-based action buttons across the Videos table (`videos-page.tsx`, `extraction-controls.tsx`, `slide-controls.tsx`, `pdf-controls.tsx`), Channels table (`channels-page.tsx`), and PDF Library table (`pdf-library-page.tsx`) with single-row icon-only buttons carrying descriptive tooltips, accessible `aria-label`s, and confirmation dialogs for destructive actions.
- **Default PDF Compression (`compact`, JPEG 85)**: Set `compact` (JPEG quality 85 at original screenshot resolution) as the default compression mode in `PdfConfig`, `PdfState`, `PdfLibraryItem`, `PdfGenerationResult`, `_parse_compression`, `.env.example`, and frontend Zod schemas; added Alembic revision `a1b2c3d4e5f6` to update persisted `pdf_generation_settings` from `"lossless"` to `"compact"` without modifying existing generated PDFs. Removed compression dropdowns from `PdfControls` and `SettingsPage` while retaining internal/API compression support for backward compatibility.
- **Table Cleanup & Channel Labels**: Reduced table row padding (`py-1.5`) while preserving status badges and processing statistics, and updated `videos-page.tsx` + `videoSchema` (`frontend/src/services/videos.ts`) to display preserved `video.channel_name` or `"Unknown Channel"` fallback instead of `"Deleted channel"`.

### Changed — Phase 7 Stabilization and PDF Optimization (2026-11-27)

- **Configurable PDF Compression**: Added `PdfCompressionMode` (`lossless` PNG default, `maximum_quality` JPEG 95, `high_quality` JPEG 90, `compact` JPEG 85) in `backend/app/domain/pdfs.py` and single-pass JPEG encoding from source PNGs in `PyMuPdfGenerator` (`backend/app/infrastructure/pdf_generator.py`), preserving original resolution and aspect ratio and recording `compression=<mode>` in PDF metadata.
- **Persistent PDF Settings & Override UI**: Added `GET`/`PUT /api/v1/settings/pdf` (`backend/app/api/settings.py`, `SettingsRepository`), compact **PDF Generation** settings section in `SettingsPage` (`frontend/src/features/settings/settings-page.tsx`), and per-generation compression override & compression badge in `PdfControls` (`frontend/src/features/videos/pdf-controls.tsx`).
- **Channel Metadata Preservation**: Added `videos.channel_name` and `videos.youtube_channel_id` via Alembic revision `f6a7b8c9d0e1` with safe backfill for linked videos, snapshotting in `ChannelRepository.update`/`delete` and `VideoRepository.create_or_skip`, and explicit `"Unknown Channel"` fallback (replacing `"Deleted channel"`) in `PdfRepository` and `PdfService`.
- **Verified**: 4-mode benchmark across 3 channels (`BSSEI Competitive vqYNwaqFPJM`, `TWS Academy 3jqcXCkRUDI`, `VSCE Academy 3S2vx41zkgY`) with visual inspection of Bengali/English text; `high_quality` (JPEG 90) recommended (~62–80% size reduction with sharp text; `lossless` retained as default). Backend `263 passed, 1 skipped` (Pytest), Ruff lint/format, strict `mypy`, Alembic `f6a7b8c9d0e1 (head)`; Frontend `56 passed` (`11` Vitest files), ESLint, Prettier, `tsc -b`, Vite build; `14` local and `14` Docker Playwright E2E tests; Docker API/ZIP/preview/settings verification. See `docs/PHASE7_REPORT.md`.

### Added — Phase 7 PDF Generation and PDF Library (2026-11-27)

- **Reusable PDF Generation Module**: Added `pymupdf` (`1.28.2`), `backend/app/domain/pdfs.py`, and `backend/app/infrastructure/pdf_generator.py` (`PyMuPdfGenerator`, `validate_pdf_file`, `build_pdf_filename`, `format_timestamp`) with no dependency on FastAPI, SQLite, YouTube, or React. Generates one landscape PDF per video (or arbitrary local image collection) at original resolution with lossless image embedding, `Timestamp: HH:MM:SS` and `Page N / M` in a dedicated footer strip outside the screenshot area, video title/channel/source URL metadata, temporary-file validation, and atomic publication.
- **Database, Service, and API**: Added `pdf_generations` table (Alembic revision `e5f6a7b8c9d0`), `PdfRepository` (`backend/app/repositories/pdfs.py`), `PdfService` (`backend/app/services/pdfs.py`), and `backend/app/api/pdfs.py` (`/api/v1/videos/{id}/pdf*` and `/api/v1/pdfs*` including list/search/filter/sort/pagination, inline preview, individual download, and disk-streamed bulk ZIP download). Enforces video exclusion rules on new generation/retry/bulk jobs, preserves previous PDFs on failed regeneration, supports cancellation and startup recovery, and keeps source videos, extracted frames, and processed slides intact.
- **Frontend Videos & PDF Library**: Extended `UnifiedBulkToolbar` (`→ Generate PDF (N)`), added `PdfControls` column on the Videos page, and implemented `PdfLibraryPage` (`/library`) and `PdfPreviewModal` using shared UI components.
- **Verified**: Backend `259 passed, 1 skipped` (Pytest), Ruff lint/format, strict `mypy` (`77` files), Alembic `e5f6a7b8c9d0 (head)`; Frontend `55 passed` (`11` Vitest files), Prettier, ESLint, `tsc -b`, Vite build; `14` local and `14` Docker Playwright E2E tests; real-world Docker PDF generation (`vqYNwaqFPJM`, 77 pages, 92,008,735 bytes, lossless 1280×720), exclusion enforcement (`PbdheRRcLLg`, 409), ZIP download, visual inspection of rendered PDF pages, and SHA-256 persistence across `docker compose up -d --force-recreate --wait`. See `docs/PHASE7_REPORT.md`.

### Changed — Phase 6 Final UI and Workflow Refinement (2026-11-27)

- **Slide Comparison Modal & Shared Modal Sizes**: Enhanced `Modal` (`frontend/src/components/ui/modal.tsx`) with `sm`, `md`, `lg`, `xl`, and `fullscreen` (`95vw × 95vh`) variants and focus restoration; applied `size="fullscreen"` to `SlidePreview` and `size="xl"` to `FramePreview`. Redesigned `SlidePreview` (`frontend/src/features/videos/slide-preview.tsx`) to show one slide at a time, display side-by-side Original vs Processed when different or one large image when identical, remove crop/mask panels, format timestamps as `HH:MM:SS`, support Previous/Next, Left/Right arrow keys, and direct slide-number jump, and move diagnostics into collapsed details.
- **Collapsible Sidebar**: Extracted `AppSidebar` (`frontend/src/components/shared/app-sidebar.tsx`) with `220px` expanded / `60px` collapsed modes, `localStorage` persistence (`ytl2s.sidebar.collapsed`), accessible tooltips, active route highlighting, and hiding the `"Local by design"` footer when collapsed.
- **Full-Frame Slide Processing (Removed Cropping)**: Disabled automatic/perspective/profile cropping in `SlideProcessor` (`backend/app/services/imaging/pipeline.py`, `board.py`) and `SlideService` (`backend/app/services/slides.py`) so all new and reprocessed jobs process full original video frames with `reliability="full_frame"` and `fallback=False`; removed crop controls from `SlideControls` and `ChannelsPage` (`channel-board-profile-modal.tsx` deleted). Retained `channel_board_profiles` table for backward compatibility without destructive migrations.
- **Configurable Video Exclusion Keywords**: Added `app_settings` table and `videos.is_excluded` / `videos.matched_exclusion_keywords` columns (Alembic revision `d4e5f6a7b8c9`), Unicode-aware NFC/case-insensitive/word-boundary matching (`backend/app/domain/exclusion.py`, `backend/app/services/exclusion.py`) supporting English and Bengali, `GET`/`PUT /api/v1/settings/exclusion-keywords` (`backend/app/api/settings.py`), automatic classification on discovery and reevaluation on keyword updates, backend enforcement across downloads/extractions/slides/bulk/recovery, Settings page `"Exclude Keywords"` UI (`frontend/src/features/settings/settings-page.tsx`), and Videos page excluded row styling, badge, eligibility filter (`All` / `Eligible` / `Excluded`), summary counts, and bulk-toolbar exclusion.
- **Verified**: Backend `252 passed, 1 skipped` (Pytest), Ruff format (`70` files), Ruff lint, strict `mypy` (`61` files); Frontend `52 passed` (`9` Vitest files), Prettier, ESLint, `tsc -b`, Vite build; `13` Playwright E2E tests passed both locally and against Docker Compose (`http://127.0.0.1:8080`), Alembic at `d4e5f6a7b8c9 (head)`, and exclusion settings persistence verified across `docker compose up -d --force-recreate`.

### Changed — Phase 6 UI Refinement and Workflow Simplification (2026-11-27)

- Removed global `max-w-5xl` container restriction and reduced excessive padding/margins across `app.tsx`, `dashboard.tsx`, `channels-page.tsx`, and `videos-page.tsx` to utilize full desktop content width.
- Created reusable shared UI components in `frontend/src/components/ui/select.tsx` and `frontend/src/components/shared/` (`PageContainer`, `PageHeader`, `StatCard`, `StatusBadge`, `ActionButton`, `ProgressIndicator`, `NotificationAlert`, `ConfirmDialog`, `DataTable`, `FilterToolbar`, `BulkActionToolbar`).
- Refined Channels page: replaced raw channel URLs and internal YouTube IDs in the table with compact `Visit channel` and `Watch video` links, kept row actions on a single horizontal row on desktop, and wired the Status filter to the shared `Select` component.
- Refined Videos page: ordered layout (`PageHeader` → `StatCard` summary → `FilterToolbar` → `UnifiedBulkToolbar` → `DataTable` → pagination), replaced oversized discovery banner with dismissible expandable `NotificationAlert`, removed misleading overall `Pending` badge from the Slides column, and compacted `ExtractionControls` and `SlideControls` (expandable details, compact action row).
- Consolidated separate bulk toolbars into `UnifiedBulkToolbar` (`Download → Extract Frames → Process Slides`) with per-action eligibility counts, disabled states, mixed-selection filtering, video-title-based feedback, and singular/plural wording.
- Removed mandatory "Manual review required" UI wording in `SlideControls` and `SlidePreview`, replacing it with non-blocking informational "Potentially obstructed" diagnostics while automatically retaining uncertain and partially obstructed screenshots.
- Verified with `47` frontend Vitest tests (`8` files), ESLint (0 errors, 0 warnings), Prettier, `tsc -b`, Vite build, `247` backend Pytest tests (1 opt-in real-data test skipped), Ruff lint, strict `mypy` (`64` files), and `12` Playwright E2E tests locally and against Docker Compose (`1280`, `1440`, `1920` viewports).

### Changed — Phase 6 Final Stabilization (2026-11-27)

- Removed bounding-box inflation in `obstruction.py` (`large_components`) with `mask_dilation_pixels=20` and made `reconstruct()` filter to compatible observations (`fusion_max_residual=0.0008`).
- Distributed `sample_timestamps()` across segment interiors, prioritized moderately obstructed segments (`<= 0.25`) in `_run_adaptive_sampling()`, and implemented two-stage low-res/full-res `_scan_missed_transitions()`.
- Added `SlideService.assert_no_published_slides` delete guard on `ExtractionService.delete()` (`409 Conflict`) to protect immutable frame references.
- Added `ChannelBoardProfileModal` on the frontend Channels page for viewing, saving/updating, and deleting per-channel crop profiles.
- Verified across 3 channels (`BSSEI Competitive`, `TWS Academy`, `VSCE Academy` validation), `248` backend tests (with `PHASE6_REAL_DATA`), `40` frontend tests, `11` Docker Playwright tests, and Docker restart/recreation persistence. See `docs/PHASE6_REPORT.md`.

### Documentation

- Defined the initial product requirements, proposed modular architecture and ten-phase development roadmap.
- Recorded the planned workflow for scheduled discovery, authorized video acquisition, frame processing and PDF export.

### Added — Phase 1 (2026-11-26)

- Python 3.12/uv FastAPI factory, validated settings, explicit CORS, versioned health/readiness API, consistent errors and structured rotating logs.
- SQLAlchemy SQLite engine/session lifecycle, Alembic environment and safe storage directory initialization without feature models.
- React/Vite strict TypeScript shell, responsive navigation, real health query, typed Zod API client and shared states; future sections explicitly unavailable.
- Tailwind v4 and shadcn component configuration, reusable Button, React Router and TanStack Query.
- Locked backend/frontend dependencies, quality tools, backend/frontend/browser tests and GitHub Actions checks.
- Non-root backend/frontend Docker images, FFmpeg/FFprobe installation, Nginx proxy, health checks and persistent Compose volume.

### Verification — Phase 1

- Backend: 20 tests pass; Ruff lint/format and mypy pass; Alembic upgrade/check pass.
- Frontend: 11 tests pass; ESLint, Prettier, strict TypeScript and production build pass.
- Playwright: two integration scenarios pass against local development and again against Docker production hosting; desktop/mobile screenshots inspected.
- Docker: both images built, both containers healthy/non-root, API proxy and SPA refresh verified, FFmpeg/FFprobe available, SQLite/files survive forced container recreation.
- Hosted GitHub Actions has not been run; its configured checks were exercised locally. Full evidence and dependency build warnings are in the Phase 1 report.

### Documentation — Phase 1

- Added actual local/Docker commands, configuration and API contracts to README; recorded scope overlap and implementation decisions in ARCHITECTURE.
- Detailed acceptance evidence and remaining limitations are maintained in docs/PHASE1_REPORT.md. Phase 2 has not started.

### Added — Phase 2 (2026-11-27)

- `ChannelRecord` SQLAlchemy model and Alembic migration (`channels` table with unique normalized `channel_url` and nullable unique `youtube_channel_id`, search indexes, UTC timestamps).
- Channel domain validation/normalization (`backend/app/domain/channels.py`), repository (`backend/app/repositories/channels.py`), service (`backend/app/services/channels.py`), and `/api/v1/channels` API routes (`backend/app/api/channels.py`).
- Configurable `DEFAULT_SEARCH_KEYWORD` setting (default `IDO`), sanitized validation error formatting, `python-multipart` for CSV upload, and container startup migration execution (`alembic upgrade head`).
- Frontend Channels page (`frontend/src/features/channels/`) with summary cards, table, search/status filtering, pagination, Add/Edit/Delete confirmation modals, CSV import/export/template download, and TanStack Query cache invalidation.

### Verification — Phase 2

- Backend: 49 tests pass (29 Phase 2 channel tests + 20 Phase 1 regression tests); Ruff lint/format, strict mypy (25 files), and Alembic upgrade/check pass.
- Frontend: 16 tests pass across 3 Vitest files; ESLint, Prettier, strict TypeScript, and Vite production build pass.
- Playwright: 3 E2E scenarios (`foundation.spec.ts` and `channels.spec.ts`) pass against local development servers and again against Docker Compose production hosting.
- Docker: images rebuilt, containers healthy, `/channels` SPA refresh verified, `alembic check` clean, and Bengali channel persistence verified across forced container recreation (`docker compose up --force-recreate --wait`).

### Documentation — Phase 2

- Updated `README.md`, `ARCHITECTURE.md`, `PLANS.md`, `.env.example`, and created `docs/PHASE2_REPORT.md` with full verification evidence.

### Added — Phase 3 (2026-11-27)

- `VideoRecord` SQLAlchemy model and Alembic migration (`videos` table with unique `youtube_video_id`, nullable `channel_id` FK with `ON DELETE SET NULL`, and search/filter indexes).
- Domain types and exceptions (`backend/app/domain/videos.py`), `YouTubeApiClient` over `httpx` with quota tracking and bounded retries (`backend/app/infrastructure/youtube_client.py`), `VideoRepository` (`backend/app/repositories/videos.py`), `DiscoveryService` (`backend/app/services/discovery.py`), and `/api/v1/videos` + `/api/v1/discovery` routes (`backend/app/api/videos.py`).
- Typed configuration settings (`youtube_api_key` masked in `repr`, `discovery_lookback_days`, `discovery_min_duration_seconds`, `discovery_max_results_per_channel`, `discovery_quota_limit`) and `httpx` + `isodate` backend dependencies.
- Frontend Videos page (`frontend/src/features/videos/videos-page.tsx`) and Zod-validated API client (`frontend/src/services/videos.ts`) with summary cards, IST date formatting, search/status/sort/pagination controls, and manual discovery trigger.

### Verification — Phase 3

- Backend: 108 tests pass (59 Phase 3 discovery/repository/client/API/security/quota tests with mocked YouTube responses + 49 Phase 1 & 2 tests); Ruff format/lint, strict mypy (32 files), and Alembic upgrade/check pass.
- Frontend: 26 tests pass across 4 Vitest files (10 Videos page tests including channel dropdown filter, individual channel discovery, and publication date filter + 16 existing tests); ESLint, Prettier, strict TypeScript, and Vite production build pass.
- Playwright: 9 E2E scenarios (`foundation.spec.ts`, `channels.spec.ts`, `videos.spec.ts`) pass against both local development servers and Docker Compose production hosting (`http://127.0.0.1:8080`).
- Docker: images rebuilt, containers healthy, `alembic check` clean, and SQLite video persistence verified across forced container recreation (`docker compose up --force-recreate --wait`).
- Live YouTube Data API v3 verification: passed against Docker Compose (`docker-compose.yml` updated to pass `YOUTUBE_API_KEY` and `DISCOVERY_*` env vars) with two active channels (`freeCodeCamp.org`, `CS50`), confirming canonical channel ID resolution, video metadata persistence, duplicate prevention on repeat runs, quota accounting (`api_requests_made=5` then `3`), UI rendering, and zero API key exposure in logs or responses.

### Documentation — Phase 3

- Updated `.env.example`, `README.md`, `ARCHITECTURE.md`, `PLANS.md`, `CHANGELOG.md`, and created `docs/PHASE3_REPORT.md`.

### Added — Phase 4 (2026-11-27)

- Added `yt-dlp==2026.11.23` backend dependency and typed download configuration (`DOWNLOAD_MAX_RESOLUTION`, `DOWNLOAD_AUDIO_ENABLED`, `DOWNLOAD_CONCURRENT_LIMIT`, `DOWNLOAD_RETRY_ATTEMPTS`, `DOWNLOAD_TIMEOUT_SECONDS`, `DOWNLOAD_MIN_FREE_DISK_MB`, `DOWNLOAD_DIR`).
- Extended `VideoRecord` and `VideoEntity` with download lifecycle fields (`download_status`, `local_video_path`, `actual_resolution`, `file_size_bytes`, `video_codec`, `download_progress`, `download_started_at`, `download_completed_at`, `download_retry_count`, `download_error`) via Alembic revision `91dda657a047_add_video_download_columns.py`.
- Implemented `YtDlpVideoDownloader` (`backend/app/infrastructure/ytdlp_downloader.py`) using `yt_dlp.YoutubeDL` Python integration (<=720p video-only, no audio/subtitles/playlists/metadata, path-traversal-safe ID-based filenames, `.part` resume, cancellation, timeout) and `FFprobeValidator` (`backend/app/infrastructure/media_probe.py`).
- Implemented `VideoDownloadService` (`backend/app/services/downloader.py`) with non-blocking `ThreadPoolExecutor` execution, per-video concurrency lock, duplicate download prevention, disk space validation, bounded retries, startup stale-download reconciliation, and safe local file deletion.
- Added `/api/v1/videos/{id}/download`, `/api/v1/videos/downloads/bulk`, `/api/v1/videos/{id}/download/progress`, `/api/v1/videos/downloads/active`, `/api/v1/videos/{id}/download/cancel`, `/api/v1/videos/{id}/download/retry`, and `DELETE /api/v1/videos/{id}/download`.
- Extended frontend `VideosPage` (`frontend/src/features/videos/videos-page.tsx`) and `frontend/src/services/videos.ts` with row/bulk selection, download/cancel/retry/delete-with-confirmation actions, real-time progress/speed/ETA polling while active, resolution/file-size metadata, and error display.

### Verification — Phase 4

- Backend: 123 tests pass (15 new Phase 4 tests including synthetic FFmpeg/FFprobe fixtures + 108 Phase 1–3 regression tests); Ruff lint/format, strict mypy (38 files), and Alembic check pass.
- Frontend: 30 tests pass across 4 Vitest files; ESLint, Prettier, strict TypeScript, and Vite production build pass.
- Playwright: 9 E2E scenarios pass locally and 9 pass against Docker Compose.
- Live Docker verification: downloaded authorized sample `jNQXAC9IVRw` inside Docker (`320x240`, `av1`, `223779` bytes, no audio), verified file and DB persistence across `docker compose up --force-recreate --wait`, and verified safe deletion.

### Added — Phase 4 Stabilization (2026-11-27)

- Persisted `downloaded_bytes`, `total_bytes`, and `download_requested` on `VideoRecord` via Alembic revision `b0f3f4fb90a4_add_download_byte_tracking_and_recovery_.py`, with throttled SQLite progress updates (`>= 2s` or `>= 5%` delta) and `is_live` distinction for transient speed/ETA.
- Added graceful `SIGTERM`/shutdown handling (`DownloadInterruptedError`) that stops accepting new requests, preserves `.part` files and `download_requested=True` state, and automatically recovers interrupted/pending downloads on startup (`recover_interrupted_downloads()`) while respecting `DOWNLOAD_RETRY_ATTEMPTS` and never restarting explicitly cancelled downloads.
- Replaced the fixed 600s wall-clock cap with `DOWNLOAD_CONNECT_TIMEOUT_SECONDS` (30s), `DOWNLOAD_INACTIVITY_TIMEOUT_SECONDS` (120s), and optional `DOWNLOAD_MAX_TOTAL_TIMEOUT_SECONDS` (`None` by default), plus periodic mid-download disk-space checks.
- Verified with 125 backend tests, 30 frontend tests, 9 local + 9 Docker Playwright E2E tests, and a live 720p Docker recovery test (`aqz-KE-bpKQ`, `1280x720`, `av1`, `71283827` bytes, no audio) across `docker compose restart backend`.

### Documentation — Phase 4

- Updated `README.md`, `ARCHITECTURE.md`, `PLANS.md`, `CHANGELOG.md`, `.env.example`, and created `docs/PHASE4_REPORT.md`.

### Known open items

- Validate authorized media acquisition and YouTube discovery with actual credentials/permissions.
- Benchmark smartboard processing, obstruction removal and deduplication with representative videos.
- Confirm 720p readability and practical throughput.

## Entry convention

For subsequent completed tasks, use Added, Changed, Fixed, Removed, Security, Documentation or Verification headings as relevant. Include the phase and actual outcome. Add a dated version section only for a real release; leave ongoing development under Unreleased. Keep detailed test evidence in the phase completion report.


### Added — Phase 5 Frame Extraction (2026-11-27)

- Independent FFmpeg interval and explicit-timestamp extraction with source PTS,
  original-resolution lossless PNGs, atomic manifests, integrity validation and cancellation.
- Independent persistent extraction states, conditional job claims, bounded workers,
  throttled progress, transient resource retries and restart reconciliation. Shared media
  locking prevents conflicting acquisition/deletion. Source videos remain intact.
- Extraction API and Videos page actions for individual/bulk requests, configurable
  intervals, counts/progress, cancel/retry, confirmed frame deletion and lazy paginated
  previews with original-resolution links.
- Benchmark-selected sparse seeking (configurable sequential alternative): the authorized
  5179-second 1280×720 AV1 lecture produced 87 frames in 35.15 seconds on the host;
  sequential sampling took 276.33 seconds. Docker recovery completed the same lecture
  and retained validated frames across recreation. See docs/PHASE5_REPORT.md.
- Updated configuration, architecture, roadmap, API documentation and verification report.
  No new dependencies; no Phase 6 algorithms, OCR, AI or PDF generation.

### Changed — Phase 5 stabilization (2026-11-27)

- Added a digest-pinned multi-architecture Deno runtime and matching locked yt-dlp EJS
  solver; explicitly configured runtime selection and disabled remote component downloads.
- Sanitized acquisition failures and upstream logging while retaining actionable dependency,
  permission and connectivity messages.
- Shared process-group termination between FFmpeg and cancellation-aware FFprobe, with
  distinct cancellation, shutdown and timeout handling and forced cleanup of children.
- Added conservative 48-hour extraction-intermediate retention with dry-run, counts/bytes,
  descriptor-based symlink protection and coordination through the existing owner lock.
- Protected active/recoverable jobs, successful generations, newest failed attempts and all
  source videos. Added disk checks during final PNG copying and actionable quota/space errors.
- Retained restart-based incomplete extraction recovery; documented checkpointing tradeoffs
  and added regression coverage for mismatched, corrupt and incomplete recovery candidates.
- Added non-root Docker runtime/EJS smoke checks to image construction and CI.
- Stabilization verification and measured results are recorded in `docs/PHASE5_REPORT.md`.


## Phase 6 — 2026-11-27

- Added local headless OpenCV/NumPy/scikit-image smartboard isolation, perspective correction,
  normalized/channel crops, conservative grouping/deduplication, foreground hypotheses,
  observed-pixel and temporal-median reconstruction, bounded five-second adaptive sampling
  and validated manifests with source references and per-primary retention decisions.
- Added independent durable slide jobs, atomic publication with previous-generation
  preservation, cancellation/recovery/resource retries, media-operation guards, safe deletion,
  paginated generation-qualified preview APIs, and Videos page processing/comparison/crop UI.
- Verified 241 backend tests (including opt-in authorized samples), 40 frontend tests,
  11 local and 11 Docker browser scenarios, lint/format/types/build/migrations, and 489 file
  hashes across Docker recreation. Authorized lecture: 87 inputs + 40 additional samples →
  86 candidates, one redundant outro excluded, one partial fusion, all candidates require
  manual review. No complete question coverage or verified reconstruction-accuracy claim.
- Updated configuration, architecture and operational documentation. See docs/PHASE6_REPORT.md
  for thresholds, resource/storage measurements, visual artifacts, failures and limitations.
  Phase 7 remains unstarted; no commit or push.


### Changed — Phase 6 Optimization & Stabilization (2026-11-27)

- Added persistent per-channel smartboard crop/perspective profiles (`channel_board_profiles` table, Alembic revision `c3d8e1f2a4b5`, `ChannelBoardProfileRepository`, and `GET/PUT/DELETE /api/v1/channels/{id}/board-profile`), automatic reuse for videos from the same channel, and aspect-ratio/edge-structure fallback validation.
- Separated chronological slide segmentation (`compare_visible` with mutually visible region SSIM, 4×4 grid cell change inspection, edge Jaccard, and new-annotation/highlight stroke detection) from duplicate representative selection; prevented uncontrolled transitive drift by checking both segment anchor and previous frame.
- Prioritized best-frame selection (`select_best_or_reconstruct` and `score_candidate`) using visible board coverage and visible-region sharpness/contrast before attempting observed-pixel fusion.
- Replaced chronological early-segment adaptive budget exhaustion with duration-scaled, whole-video priority-based sampling across 4 temporal quarters, stopping early once a clear observation is found.
- Added meaningful quality categories (`clear_original`, `improved_original`, `reconstructed`, `incomplete`, `uncertain`) and separate `crop_reliability`, `visible_coverage`, and `grouping_confidence` indicators; updated frontend Zod schemas and `SlidePreview`.
- Reduced intermediate output storage by referencing immutable Phase 5 frames for unmodified originals, avoiding duplicate crop/slide copies, and making diagnostic masks opt-in (`save_diagnostics=False` by default).
- Verified 245 backend tests (1 opt-in skipped), Ruff lint/format, strict mypy (56 source files), 40 frontend Vitest tests, ESLint/Prettier/`tsc -b`/Vite build, and 11 local Playwright E2E tests. Authorized 86-minute lecture benchmark (`vqYNwaqFPJM`): 87 inputs → 76 slides (11 duplicates excluded, 0 distinct questions lost), 65 distributed adaptive samples, 58 manual reviews (down from 86), 152.6 MB output (down from 351.8 MB, -56.6%). See `docs/PHASE6_REPORT.md`.
