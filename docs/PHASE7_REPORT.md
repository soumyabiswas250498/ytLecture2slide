# Phase 7 completion report — PDF generation and PDF Library

Date: 2026-11-27 (Asia/Kolkata). Status: **Implemented and verified within documented limits.**
Scope: Phase 7 only. No commit or push.

## 1. Implementation summary

Implemented a reusable, lossless image-to-PDF generation module backed by PyMuPDF (`pymupdf`), independent SQLite persistence (`pdf_generations`), background job execution with cancellation and startup recovery, REST endpoints for generation/preview/download/bulk ZIP/library management, Videos page row & bulk PDF controls, and the full PDF Library page at `/library`.

- **Core PDF module (`backend/app/infrastructure/pdf_generator.py`, `backend/app/domain/pdfs.py`)**:
  - Independent of FastAPI, SQLite, YouTube, and React; supports both slide-manifest inputs and arbitrary local image collections (`PyMuPdfGenerator.generate` and `PyMuPdfGenerator.generate_from_paths`).
  - Produces one landscape PDF per video, one slide per page, preserving original image resolution, aspect ratio, and lossless PNG/image embedding without cropping, upscaling, or downscaling.
  - Renders `Timestamp: HH:MM:SS` and `Page N / M` in a dedicated `28pt` footer strip outside the screenshot rectangle, and embeds video title, channel name, source URL, and YouTube video ID in PDF metadata.
  - Writes to a temporary file, validates readability, expected page count, landscape orientation, and per-page embedded image dimensions via `validate_pdf_file`, and publishes atomically via `Path.replace`.
  - Sanitizes readable filenames (`YYYY-MM-DD_<Channel>_<Title>_<VideoID>.pdf`) against path traversal and collisions.
- **Database, service, and API (`backend/migrations/versions/e5f6a7b8c9d0_pdf_generations.py`, `backend/app/repositories/pdfs.py`, `backend/app/services/pdfs.py`, `backend/app/api/pdfs.py`)**:
  - Independent `pdf_generations` table tracking `source_slide_generation`, `status` (`pending`, `generating`, `generated`, `failed`, `cancelled`), `requested`, `progress`, `completed_pages`/`total_pages`, `pdf_path`, `pdf_filename`, `page_count`, `file_size_bytes`, `configuration`, `started_at`, `completed_at`, `retry_count`, and `error`.
  - Bounded `ThreadPoolExecutor` (`PDF_CONCURRENT_LIMIT=1`) sharing `media_lock` with `SlideService` (`slide_service.pdf_guard`), bounded resource-error retries, user cancellation, and startup recovery.
  - Enforces video exclusion rules on new generation, retry, and bulk requests while keeping existing generated PDFs accessible for preview, download, ZIP export, and deletion.
  - Preserves previous successful PDFs on disk and in the PDF Library if a subsequent regeneration fails.
  - Streams bulk ZIP archives on disk via `zipfile.ZipFile(..., ZIP_STORED)` with duplicate-filename disambiguation, configurable file/byte limits (`PDF_ZIP_MAX_FILES=100`, `PDF_ZIP_MAX_TOTAL_BYTES=2147483648`), and `BackgroundTasks` cleanup.
  - Never deletes source videos, extracted frames, or processed slides.
- **Frontend (`frontend/src/services/pdfs.ts`, `frontend/src/features/videos/pdf-controls.tsx`, `frontend/src/features/videos/unified-bulk-toolbar.tsx`, `frontend/src/features/library/pdf-library-page.tsx`, `frontend/src/features/library/pdf-preview-modal.tsx`)**:
  - Added `PDF` column with `PdfControls` on the Videos page and `→ Generate PDF (N)` in `UnifiedBulkToolbar`.
  - Implemented `/library` (`PdfLibraryPage`) with summary cards, title search, channel filter, publication date range filter, sorting, pagination, individual/select-all selection, bulk ZIP download, fullscreen PDF preview modal, individual download, and delete confirmation.

## 2. Files created and modified

Created:
- `backend/app/domain/pdfs.py`
- `backend/app/infrastructure/pdf_generator.py`
- `backend/app/repositories/pdfs.py`
- `backend/app/services/pdfs.py`
- `backend/app/api/pdfs.py`
- `backend/migrations/versions/e5f6a7b8c9d0_pdf_generations.py`
- `backend/tests/test_pdfs.py`
- `frontend/src/services/pdfs.ts`
- `frontend/src/features/videos/pdf-controls.tsx`
- `frontend/src/features/videos/pdf-controls.test.tsx`
- `frontend/src/features/library/pdf-preview-modal.tsx`
- `frontend/src/features/library/pdf-library-page.tsx`
- `frontend/src/features/library/pdf-library-page.test.tsx`
- `frontend/e2e/pdfs.spec.ts`
- `docs/PHASE7_REPORT.md`

Modified:
- `backend/pyproject.toml`, `backend/uv.lock`
- `backend/app/core/config.py`, `backend/app/core/errors.py`, `backend/app/infrastructure/models.py`, `backend/app/infrastructure/storage.py`, `backend/app/services/slides.py`, `backend/app/main.py`
- `backend/tests/test_foundation.py`
- `frontend/src/app.tsx`, `frontend/src/app.test.tsx`, `frontend/e2e/foundation.spec.ts`
- `frontend/src/features/videos/videos-page.tsx`, `frontend/src/features/videos/unified-bulk-toolbar.tsx`
- `.env.example`, `docker-compose.yml`, `README.md`, `REQUIREMENTS.md`, `ARCHITECTURE.md`, `PLANS.md`, `CHANGELOG.md`

## 3. Dependencies added

| Package | Version | Justification |
|---|---|---|
| `pymupdf` | `1.28.2` | Lossless image-to-PDF generation, metadata embedding, and PDF structure/image validation (required by Phase 7 specification) |

## 4. Verification and actual test results

| Check | Actual Result |
|---|---|
| Backend Ruff format & lint | Passed (`77` files) |
| Backend strict `mypy` | Passed (`77` source/test files, 0 issues) |
| Backend `pytest` | `259 passed, 1 skipped` (opt-in `PHASE6_REAL_DATA` skipped; all Phase 1–6 regressions and 7 new Phase 7 test suites passed) |
| Backend Alembic `upgrade head` & `check` | Passed (`e5f6a7b8c9d0 (head)`, no drift) |
| Frontend Prettier & ESLint | Passed (0 errors, 0 warnings) |
| Frontend TypeScript (`tsc -b`) & Vite build | Passed |
| Frontend Vitest | `55 passed` across `11` test files |
| Local Playwright E2E | `14 passed` in `6.7s` |
| Docker Playwright E2E (`http://127.0.0.1:8080`) | `14 passed` in `3.7s` |
| Docker container Alembic `check` | Passed (`No new upgrade operations detected.`) |

## 5. Real-world Docker verification & measurements

- **Eligible lecture (`vqYNwaqFPJM`, 86-minute 1280×720 AV1 lecture, 77 published slides)**:
  - Generation duration: `10.798 s`
  - Page count: `77` (100% match to published slide manifest, including uncertain/obstructed slides)
  - Embedded image resolution: `(1280, 720)` on all 77 pages, landscape orientation (`1280 × 748 pt` with `28 pt` footer)
  - File size: `92,008,735 bytes` (`87.7 MB`)
  - Individual download & bulk ZIP download: verified (`92,008,735` bytes PDF; valid ZIP archive containing `2026-11-27_Unknown Channel_Authorized Phase 5 lecture_vqYNwaqFPJM.pdf`)
  - Visual inspection: rendered `storage/phase7/page1.png` and `storage/phase7/page15.png` inspected; Bengali and English MCQ text is sharp and readable, and `Timestamp: HH:MM:SS` / `Page N / 77` sit cleanly below the screenshot area.
  - UI inspection: `storage/phase7/ui-videos.png` and `storage/phase7/ui-library.png` inspected against live Docker Compose (`http://127.0.0.1:8080`).
- **Excluded video enforcement (`PbdheRRcLLg`, TWS Academy, excluded by keyword `Math`)**:
  - `POST /api/v1/videos/15/pdf` rejected with `HTTP 409` (`{"error":{"code":"video_excluded","message":"Excluded by keyword(s): Math"}}`).
- **Docker container recreation persistence (`docker compose up -d --force-recreate --wait`)**:
  - `pdf_generations` DB row and `/data/pdfs/2026-11-27_Unknown Channel_Authorized Phase 5 lecture_vqYNwaqFPJM.pdf` survived container recreation with identical SHA-256 (`85bf8a798c7288bcfae10a023803732186dcb728fd4ed18247bd8fc020d817ce`).
  - Source videos, extracted frames, and processed slides remained intact.

## 6. Known issues and limitations

- In the live Docker database, `vqYNwaqFPJM` has `channel_id=NULL` (`Deleted channel` / `Unknown Channel` in PDF metadata) because its original Phase 5 channel was deleted in an earlier phase; TWS Academy's processed lecture (`PbdheRRcLLg`) is excluded by the configured `Math` keyword, and no VSCE Academy lecture was pre-downloaded/extracted/processed in the volume.
- Source videos, extracted frames, and processed slides are intentionally retained in Phase 7; automatic post-PDF cleanup belongs to Phase 8.
- Multi-worker backend deployments remain unsupported (single-owner process model).

---

## 7. Stabilization and PDF Optimization Addendum (2026-11-27)

### Summary of changes
- **Configurable PDF compression (`backend/app/domain/pdfs.py`, `backend/app/infrastructure/pdf_generator.py`)**: Added `lossless` (original PNG, retained as default), `maximum_quality` (JPEG 95), `high_quality` (JPEG 90), and `compact` (JPEG 85). Lossy modes encode in a single pass from the original PNG source without cropping, downscaling, upscaling, or repeated lossy compression, and record `compression=<mode>` in PDF metadata `creator`.
- **Settings persistence & per-generation override (`backend/app/repositories/settings.py`, `backend/app/api/settings.py`, `backend/app/services/pdfs.py`, `frontend/src/features/settings/settings-page.tsx`, `frontend/src/features/videos/pdf-controls.tsx`)**: Added `GET`/`PUT /api/v1/settings/pdf`, compact PDF Generation section on `/settings` using the shared `Select` component, and optional per-generation override + compression label on Videos `PdfControls`. Changing settings never alters existing PDFs automatically.
- **Channel metadata preservation (`backend/app/infrastructure/models.py`, `backend/migrations/versions/f6a7b8c9d0e1_preserve_video_channel_metadata.py`, `backend/app/repositories/channels.py`, `backend/app/repositories/videos.py`, `backend/app/repositories/pdfs.py`, `backend/app/services/pdfs.py`)**: Persisted `channel_name` and `youtube_channel_id` on `videos`, backfilled linked rows in Alembic revision `f6a7b8c9d0e1` without fabricating missing metadata, snapshotted metadata on channel update/delete, and replaced `"Deleted channel"` with preserved `channel_name` or `"Unknown Channel"` fallback.

### Multi-channel 4-mode benchmark results (`storage/phase7-benchmark/`)

| Channel | Video ID | Mode | Pages | Dimensions | Source PNGs | PDF Size | Reduction vs Lossless | Duration | Peak Traced Mem |
|---|---|---|---|---|---|---|---|---|---|
| BSSEI Competitive | `vqYNwaqFPJM` | `lossless` | 79 | 1280×623 | 77.15 MB | 81.24 MB (85,182,555 B) | 0.00% | 9.582 s | 3.05 MB |
| BSSEI Competitive | `vqYNwaqFPJM` | `maximum_quality` | 79 | 1280×623 | 77.15 MB | 23.50 MB (24,643,285 B) | 71.07% | 3.998 s | 1.11 MB |
| BSSEI Competitive | `vqYNwaqFPJM` | `high_quality` | 79 | 1280×623 | 77.15 MB | 16.68 MB (17,486,781 B) | 79.47% | 3.840 s | 0.84 MB |
| BSSEI Competitive | `vqYNwaqFPJM` | `compact` | 79 | 1280×623 | 77.15 MB | 13.61 MB (14,270,106 B) | 83.25% | 3.341 s | 0.70 MB |
| TWS Academy | `3jqcXCkRUDI` | `lossless` | 30 | 1280×648, 1280×720 | 15.03 MB | 11.09 MB (11,623,767 B) | 0.00% | 2.598 s | 2.37 MB |
| TWS Academy | `3jqcXCkRUDI` | `maximum_quality` | 30 | 1280×648, 1280×720 | 15.03 MB | 5.48 MB (5,748,437 B) | 50.55% | 1.089 s | 0.75 MB |
| TWS Academy | `3jqcXCkRUDI` | `high_quality` | 30 | 1280×648, 1280×720 | 15.03 MB | 4.22 MB (4,423,779 B) | 61.94% | 1.058 s | 0.57 MB |
| TWS Academy | `3jqcXCkRUDI` | `compact` | 30 | 1280×648, 1280×720 | 15.03 MB | 3.61 MB (3,781,082 B) | 67.47% | 1.020 s | 0.48 MB |
| VSCE Academy | `3S2vx41zkgY` | `lossless` | 61 | 1280×680 | 50.94 MB | 46.58 MB (48,840,567 B) | 0.00% | 6.321 s | 2.05 MB |
| VSCE Academy | `3S2vx41zkgY` | `maximum_quality` | 61 | 1280×680 | 50.94 MB | 13.08 MB (13,717,398 B) | 71.91% | 2.684 s | 0.82 MB |
| VSCE Academy | `3S2vx41zkgY` | `high_quality` | 61 | 1280×680 | 50.94 MB | 9.26 MB (9,706,227 B) | 80.13% | 2.456 s | 0.61 MB |
| VSCE Academy | `3S2vx41zkgY` | `compact` | 61 | 1280×680 | 50.94 MB | 7.56 MB (7,929,514 B) | 83.76% | 2.337 s | 0.52 MB |

### Visual comparison & recommendation
- **Comparison images**: `storage/phase7-benchmark/compare/vqYNwaqFPJM_p15_{lossless,maximum_quality,high_quality,compact}.png`, `3jqcXCkRUDI_p5_high_quality.png`, and `3S2vx41zkgY_p10_high_quality.png`.
- **Findings**: `maximum_quality` (JPEG 95) is visually indistinguishable from `lossless`. `high_quality` (JPEG 90) preserves crisp Bengali conjuncts, matras, digits, English text, and thin yellow/red handwritten annotations with negligible ringing while cutting PDF size by **61.94%–80.13%** and generation duration by ~2.5×. `compact` (JPEG 85) remains readable but introduces mild ringing around high-contrast white-on-blue Bengali glyph edges and small logos.
- **Recommendation**: Recommend **`high_quality` (JPEG quality 90)** as the best balance of Bengali/English readability and storage efficiency. Retain **`lossless`** as the default until benchmark results are reviewed by the user.

### Stabilization verification results
- **Backend**: `263 passed, 1 skipped` (Pytest, including 4 new regression tests for all compression modes, settings persistence/regeneration, channel deletion metadata preservation & unknown fallback, and Alembic backfill; `test_authorized_real_preservation_and_reconstruction` skipped because the original Phase 6 uncropped `samples-180` fixture is not retained on disk — when tested against `phase5-seek-full` + cropped `samples_00003`, `reconstruct` returned `original` due to dimension mismatch). Ruff lint/format and strict `mypy` (`65` source/test files) passed; Alembic at `f6a7b8c9d0e1 (head)` with no drift.
- **Frontend**: `56 passed` across `11` Vitest files, ESLint, Prettier, `tsc -b`, and Vite production build passed.
- **E2E & Docker**: `14` local and `14` Docker Playwright E2E tests passed (`http://127.0.0.1:8080`). Live Docker API verified `f6a7b8c9d0e1` backfill, `"Unknown Channel"` fallback for `vqYNwaqFPJM`, inline preview, individual download, bulk ZIP download, and `lossless` default persistence.
