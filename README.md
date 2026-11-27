# ytLecture2slide

Turn YouTube lectures into readable slides.

## Overview

A local, self-hosted application that converts long educational videos into chronological, image-based PDFs. The initial use case is WBPSC IDO preparation, but channels, search keywords and processing parameters must be configurable for other examinations.

The application does not extract MCQs, perform OCR, transcribe audio or call an LLM. Users download the generated PDFs and process them separately using ChatGPT Plus or another tool of their choice.

## Intended workflow

1. Import or manage educational YouTube channels.
2. Run a daily scheduled batch (default 03:00 Asia/Kolkata) or select Run Now.
3. Find eligible completed videos from the configured channels in the last seven days.
4. Acquire authorized video-only media at up to 720p into temporary storage.
5. Sample frames every 60 seconds; sample more densely where needed.
6. Crop the smartboard, attempt obstruction removal and conservatively remove redundant slides.
7. Produce one image-based PDF per video with source timestamps.
8. Verify and publish each PDF, then clean up temporary files.
9. Preview and download individual PDFs or a ZIP of selected PDFs.

## Planned stack

- Frontend: React, TypeScript (strict), Vite, Tailwind CSS, shadcn/ui.
- Backend: Python, FastAPI, Pydantic, uv.
- Processing: yt-dlp, FFmpeg, OpenCV, NumPy, scikit-image, ImageHash, PyMuPDF.
- Persistence: SQLite; scheduling: APScheduler.
- Deployment: Docker Compose on an Ubuntu homelab.
- Quality: Ruff, mypy, Pytest, ESLint, Prettier, Vitest, Playwright, GitHub Actions.

## Repository documentation

| File | Purpose |
|---|---|
| AGENTS.md | Mandatory engineering and Codex instructions (provided separately) |
| README.md | Project overview and setup |
| REQUIREMENTS.md | Functional and non-functional requirements |
| ARCHITECTURE.md | System design and module boundaries |
| PLANS.md | Phase-wise scope and acceptance criteria |
| CHANGELOG.md | Actual development history |

## Development status

Phase 1 foundation, Phase 2 channel management, Phase 3 video discovery, and Phase 4 video acquisition are implemented and verified. Phase 5 frame extraction and Phase 6 smartboard processing are implemented and verified within the documented conservative limits; scheduling and PDF generation remain future work. See the [Phase 6 report](docs/PHASE6_REPORT.md) for visual examples, measurements and limitations. Future navigation sections explicitly state that they are unavailable. See [Phase 1 report](docs/PHASE1_REPORT.md), [Phase 2 report](docs/PHASE2_REPORT.md), [Phase 3 report](docs/PHASE3_REPORT.md), and [Phase 4 report](docs/PHASE4_REPORT.md) for verification evidence and limitations.

## Local setup

Requirements: Python 3.12, uv, Node.js 22.12+ (tested with 22.14), npm. FFmpeg and FFprobe are required system tools for later processing; Docker installs both now. No credentials are needed for Phase 1.

From the repository root:

```sh
cp .env.example .env
cd backend
uv sync --frozen
uv run alembic upgrade head
uv run python -m app
```

In a second terminal, from the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. The Vite development proxy forwards `/api` to the backend at http://127.0.0.1:8000. The backend binds the configured host/port; the CLI entry point loads settings at startup. API documentation: http://127.0.0.1:8000/docs.

## Configuration

The backend and Vite load the root `.env`. Environment variables override file values. Paths are resolved relative to the repository root, independently of the launch directory. Vite exposes only `VITE_*` values to the browser. Rebuild frontend assets after changing those values.

| Variable | Default / purpose |
|---|---|
| `APP_ENV` | `development`; accepts `development`, `test`, `production` |
| `BACKEND_HOST`, `BACKEND_PORT` | `127.0.0.1`, `8000`; port range 1–65535 |
| `CORS_ORIGINS` | JSON array of explicit origins; local Vite origins by default; Compose uses `[]` because the UI proxies same-origin requests |
| `VITE_API_URL` | `/api/v1`; HTTP(S) URL or absolute path, validated by Zod |
| `BACKEND_PROXY_URL` | Development-only Vite proxy target, `http://127.0.0.1:8000` |
| `STORAGE_DIR` | `./storage`; persistent root |
| `TEMP_DIR` | `<storage>/jobs` if omitted; example explicitly uses `./storage/jobs` |
| `DATABASE_PATH` | `<storage>/database/app.db` if omitted; example explicitly sets that path |
| `LOG_LEVEL` | `INFO`; DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `TIMEZONE` | `Asia/Kolkata`; valid IANA name, reserved for future scheduling/display |
| `DEFAULT_SEARCH_KEYWORD` | `IDO`; default search keyword assigned when omitted during channel creation/import |
| `YOUTUBE_API_KEY` | Optional server-side YouTube Data API v3 key; masked in settings repr and never exposed to frontend or logs |
| `DISCOVERY_LOOKBACK_DAYS` | `7`; publication window in days for video discovery (1–30) |
| `DISCOVERY_MIN_DURATION_SECONDS` | `1200`; minimum video duration threshold in seconds (accepts strictly `> 1200s`, i.e. >20 minutes) |
| `DISCOVERY_MAX_RESULTS_PER_CHANNEL` | `50`; max search results per page per channel (1–200) |
| `DISCOVERY_QUOTA_LIMIT` | `10000`; daily YouTube API general quota pool limit (resets midnight `America/Los_Angeles`) |
| `DISCOVERY_SEARCH_QUOTA_LIMIT` | `100`; dedicated daily `search.list` quota bucket limit (resets midnight `America/Los_Angeles`) |
| `DOWNLOAD_MAX_RESOLUTION` | `720`; maximum video height in pixels (144–2160) |
| `DOWNLOAD_AUDIO_ENABLED` | `false`; audio stream acquisition disabled by default |
| `DOWNLOAD_CONCURRENT_LIMIT` | `1`; maximum concurrent video downloads (1–5) |
| `DOWNLOAD_RETRY_ATTEMPTS` | `3`; bounded retry attempts for transient download errors and crash recovery (0–10) |
| `DOWNLOAD_CONNECT_TIMEOUT_SECONDS` | `30`; network socket connection timeout in seconds (5–300) |
| `DOWNLOAD_INACTIVITY_TIMEOUT_SECONDS` | `120`; network stall/inactivity timeout in seconds when byte progress stops (10–1800) |
| `DOWNLOAD_MAX_TOTAL_TIMEOUT_SECONDS` | Unset (`None`); optional overall per-download cap in seconds (30–86400); healthy progressing downloads are not terminated |
| `DOWNLOAD_MIN_FREE_DISK_MB` | `500`; minimum free disk space required before starting a download |
| `DOWNLOAD_DIR` | `<temp_dir>/videos` if omitted; destination directory for downloaded video files |
| `FRONTEND_PORT` | Compose-only published loopback port, `8080` |

When changing `STORAGE_DIR`, update explicit `TEMP_DIR` and `DATABASE_PATH` overrides too, or remove them to use derived defaults. Compose uses container paths under `/data` rather than host `.env` paths and fixes the internal backend port to 8000 for its proxy. Log level and timezone remain configurable.

Startup creates and write-tests temporary videos, extracted frames, processed slides, PDFs, logs and database directories. Invalid configuration or unusable storage/database prevents startup. Application logs are JSON on stderr and in a rotating `logs/app.log` file (5 MB, three backups). Runtime files and secrets are ignored by Git. No cleanup deletes any media in Phase 1.

## API contracts

- `GET /api/v1/health`: liveness, HTTP 200 `{"status":"ok"}`.
- `GET /api/v1/ready`: checks SQLite, HTTP 200 `{"status":"ready"}` or HTTP 503 with error code `not_ready`.
- `GET /api/v1/channels`: paginated channel list (`page`, `page_size`, `search`, `is_active`) with global `summary` (`total`, `active`, `inactive`).
- `POST /api/v1/channels`: create a channel (normalizes YouTube URLs, prevents duplicates, defaults `search_keyword` to `DEFAULT_SEARCH_KEYWORD`).
- `GET /api/v1/channels/{channel_id}`: retrieve a single channel.
- `PATCH /api/v1/channels/{channel_id}`: partial update (name, URL, YouTube channel ID, sample video URL, search keyword, active status).
- `DELETE /api/v1/channels/{channel_id}`: delete a channel (HTTP 204).
- `POST /api/v1/channels/import`: UTF-8 CSV import (`channel_name,channel_url,sample_video_url` plus optional `search_keyword`, `is_active`), skipping duplicates without overwriting and reporting row-specific validation errors.
- `GET /api/v1/channels/export`: export channels as UTF-8 CSV (`search`, `is_active` filters supported).
- `GET /api/v1/channels/template`: download an empty UTF-8 CSV template with supported headers.
- `GET /api/v1/videos`: paginated discovered video list (`search`, `channel_id`, `processing_status`, `published_after`, `published_before`, `sort_by`, `sort_order`, `page`, `page_size`).
- `GET /api/v1/videos/summary`: discovered video counts (`total`, `pending`, `today`, `latest_discovery_at`).
- `GET /api/v1/videos/{video_id}`: retrieve a single discovered video.
- `POST /api/v1/discovery/run`: trigger manual YouTube video discovery across all active channels and return run summary counts.
- `POST /api/v1/discovery/channel/{channel_id}`: trigger manual YouTube video discovery for a single registered channel.
- Errors use `{"error":{"code":"...","message":"..."}}`. Invalid request parameters return 422; duplicate registrations return 409; missing records return 404; unexpected failures return a generic 500 without internal details. Full diagnostics remain server-side.

Alembic manages SQLite schema revisions (`channels` table in Phase 2, `videos` table in Phase 3); startup never calls `create_all`. Run `uv run alembic upgrade head` locally; Docker Compose runs `alembic upgrade head` automatically on container boot.

## Docker

```sh
docker compose config --quiet
docker compose up --build --wait
docker compose exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready').read().decode())"
docker compose exec backend ffmpeg -version
docker compose exec backend ffprobe -version
```

Open http://localhost:8080. Both containers run as non-root users. Only the frontend is published, on loopback; Nginx proxies `/api/` to the private backend and supports client-side route refreshes. Both containers have health checks. The named `application-data` volume holds `/data` including SQLite, temporary workspace, PDFs and logs; it survives `docker compose down` and recreation. Do not remove the volume when preserving data. For migrations use `docker compose exec backend uv run --frozen --no-dev alembic upgrade head`. Stop with `docker compose down`.

This unauthenticated foundation is intended for a trusted local environment. Configure appropriate access protection before any external exposure. Docker is the Ubuntu deployment path; the production frontend is served by Nginx, not Vite.

## Quality checks

From `backend/`:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run alembic upgrade head
uv run alembic check
```

From `frontend/`:

```sh
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Playwright starts its own backend and Vite servers; keep local ports 8000 and 5173 free. Its backend uses ignored `storage/e2e` data. Tests use isolated temporary SQLite files and mocked network responses except for the browser integration tests, which connect the local frontend and backend. To run the same browser suite against an already running Compose deployment, use `E2E_BASE_URL=http://127.0.0.1:8080 npm run test:e2e`. GitHub Actions runs both quality suites, browser integration, and a Compose smoke test including persistence. Lockfiles are `backend/uv.lock` and `frontend/package-lock.json`.

## Content permissions

Only acquire and process videos where authorized by the relevant rights holder and service terms. The application must not bypass access controls, DRM or service restrictions. A local video input route should support authorized media without YouTube access.

## Phase 5 — Frame extraction

The Videos page supports individual and selected-video extraction, interval selection,
progress, cancellation, retry, deletion with confirmation, and paginated frame preview.
The default is one extraction job, every 60 seconds, lossless PNG at the source resolution.
Full-resolution screenshots open from the preview; each page loads at most 12 lazy images.
Source videos are always retained by extraction. Existing download controls reject source
changes while extraction is queued or running.

| Variable | Default / purpose |
|---|---|
| `FRAME_DIR` | `<temp_dir>/frames`; persistent frame root, `/data/jobs/frames` in Compose |
| `EXTRACTION_INTERVAL_SECONDS` | `60`; positive interval, minimum 0.001 seconds |
| `EXTRACTION_CONCURRENT_LIMIT` | `1`; 1–5 background extraction jobs |
| `EXTRACTION_STRATEGY` | `seek`; `seek` for sparse sampling, `sequential` for a single decode pass |
| `EXTRACTION_THREADS` | `1`; decoder/filter/encoder threads, 1–16 |
| `EXTRACTION_RETRY_ATTEMPTS` | `3`; automatic resource-error retries and restart recovery limit |
| `EXTRACTION_MIN_FREE_DISK_MB` | `500`; checked before enqueueing and throughout decoding |
| `EXTRACTION_PROGRESS_INTERVAL_SECONDS` | `2`; minimum interval between progress writes |
| `EXTRACTION_MAX_FRAMES` | `100000`; reject oversized sampling requests before allocating frame metadata |
| `EXTRACTION_MAX_FILTER_BYTES` | `32000`; larger explicit timestamp filter expressions fall back to seeking |

Sampling requests `start + n * interval < end`, including the initial frame at zero by
default. For 5179 seconds at 60-second intervals this means 87 frames, through 5160 seconds.
Each screenshot is the first decoded frame at or after its requested timestamp. Requests
that have no available frame before the exclusive end fail safely. The manifest records
both requested time and actual integer source PTS multiplied by the stream time base,
relative to playback origin. VFR gaps can therefore produce multiple filenames with the
same actual timestamp; potentially useful requested samples are preserved.

Files live under `<FRAME_DIR>/<database-video-id>/<generation>/frame_000060000.png`.
The filename's numeric portion is the requested timestamp in milliseconds. Every successful
generation has an atomically written `manifest.json` with source identity, dimensions,
configuration, timestamps, counts and timing. PNG signatures, chunk CRCs and compressed
image streams are validated before success. Cancelled/failed generations remain on disk subject to the conservative retention policy
below; **Delete frames** removes all generations for that video, preserving the source.
Keep Compose frame paths under `/data` so that the named volume persists them.
Recovery reuses a fully validated matching generation if publication preceded a crash;
otherwise it starts a new generation. It never resumes explicitly cancelled jobs.

Standalone use (from `backend/`, without HTTP or a database):

```python
from pathlib import Path
from threading import Event
from app.infrastructure.frame_extractor import FFmpegFrameExtractor

extractor = FFmpegFrameExtractor(strategy="seek")
result = extractor.extract(
    Path("lecture.mp4"), Path("frames-new-generation"), video_id="local-lecture",
    interval=60, start=0, end=None, cancel=Event(),
    on_progress=lambda count, expected: print(count, expected),
)
# Additional sampling: use a separate empty output directory.
additional = extractor.extract(
    Path("lecture.mp4"), Path("additional-frames"), video_id="local-lecture",
    timestamps=[4657.123, 4660],
)
```

Extraction API (all under `/api/v1/videos`):

- `GET /extractions/config`: configured default interval.
- `POST /extractions/bulk`: `{ "video_ids": [1, 2], "interval_seconds": 60 }`;
  per-video started IDs and errors, HTTP 202.
- `POST /{id}/extraction`: `{ "interval_seconds": 60 }` (optional interval); HTTP 202.
- `GET /{id}/extraction`: persisted status, requested flag, counts, progress, paths,
  interval, start/completion timestamps, retry count and last error.
- `POST /{id}/extraction/cancel`, `POST /{id}/extraction/retry`.
- `DELETE /{id}/extraction`: safely delete video-owned generations and reset extraction state.
- `GET /{id}/frames?page=1&page_size=12`: chronological metadata (maximum page size 48).
- `GET /{id}/frames/{filename}`: verified original-resolution PNG preview.

Missing records return 404; queued/running/completed conflicts return 409; missing or unsafe
sources return 422; insufficient space before enqueueing returns 507. Media/encoding errors
are recorded as failed jobs. Retryable OS resource errors use bounded exponential backoff;
invalid media and insufficient space require correction and an explicit retry.

Benchmark a local authorized video with
`uv run python -m scripts.benchmark_extraction SOURCE NEW_OUTPUT --strategy seek`.
Use `--strategy sequential --compare-seek` for a comparison. See
[Phase 5 report](docs/PHASE5_REPORT.md) for measured lecture results and limits.
Run a **single backend process**: the persistent claims and shared operation lock support
this deployment; coordination across independent backend worker owners is not supported.

### Phase 5 stabilization: runtime, cancellation and retention

Docker includes **Deno 2.5.6**, copied from an official multi-architecture image pinned by
manifest digest, and **yt-dlp-ejs 0.8.0**, matched to the locked yt-dlp 2026.11.23 release.
Only the runtime binary is copied; no host JavaScript installation is required.
These components follow the [official yt-dlp EJS setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
Remote solver downloads are disabled; `uv sync --frozen` installs the locked solver.
For local development, install a supported runtime separately. Configure `DOWNLOAD_JS_RUNTIME`
(`deno`, `node` or `quickjs`) and optionally `DOWNLOAD_JS_RUNTIME_PATH` to its executable.
Compose defaults to `/usr/local/bin/deno`; select a matching path when overriding the runtime.
Runtime and solver updates should be reviewed and locked together. The build executes Deno
and imports EJS as the non-root application user; CI repeats the runtime smoke check.

FFprobe and FFmpeg share bounded subprocess termination. Probe cancellation is polled every
100 ms, sends termination to the process group and escalates to kill after five seconds.
User cancellation clears request intent; shutdown interruption retains recovery intent.
The FFprobe timeout remains a distinct validation failure. Disk checks run before extraction,
while decoding, and before each PNG copy/validation; ENOSPC/quota errors request free space
and an explicit retry. No source video is removed by extraction or retention cleanup.

`CLEANUP_RETENTION_HOURS` defaults to **48**; `CLEANUP_DRY_RUN=true` reports candidates
without removing them. Cleanup runs at startup before recovery and after extraction workers
finish, including failures/cancellation. It takes the same media-operation lock as job claims
and deletion. There is no scheduler or new public API. Logs report generations, file counts,
logical bytes removed (or predicted in dry-run) and errors; filesystem allocation/hard links
can make physical disk reclamation differ from logical byte counts.

Retention applies only to expired UUID-named generations containing known intermediate
PNG/lock/temporary-manifest files under `FRAME_DIR/<video-id>`. It preserves:

- Every active/queued/recoverable job's generations, including shutdown recovery intent.
- Every generation with a published manifest, including publications requiring inspection.
- The database-referenced output and the newest incomplete attempt of a failed job.
- Recent intermediates, unknown files/directories, source videos and unsafe symlinks.

Older failed attempts, expired cancelled attempts and orphaned incomplete generations can
be removed. Cleanup opens directory components without following symlinks and deletes via
directory descriptors. The reusable `StorageCleanupService.cleanup(dry_run=True)` is intended
to run inside the same owner with its shared lock and authoritative state/active callbacks;
do not run a separate cleanup owner against an actively used storage tree. Custom standalone
extraction directories are outside automatic cleanup unless they follow this managed layout.

Recovery deliberately restarts incomplete generations. Partial samples do not contain
independently committed source/configuration identity and source PTS checkpoints. Reusing them
would require an additional recovery journal and validation protocol for both extraction
strategies, adding complexity for approximately 30 seconds saved on the measured lecture.
Completed manifests are validated and reused only when source path, size, modification time,
video ID and interval match. This preserves correctness and avoids mixing generations.

## Phase 6 — local smartboard and slide processing

On **Videos**, extract frames first, then choose **Process Slides** (or select rows and
**Process selected slides**). Counts and progress come from persisted work. **Compare slides**
opens original, crop, processed image and heuristic obstruction mask with full-resolution
links. **Adjust board crop** offers a visible rectangle and normalized coordinates; applying
it explicitly reprocesses the video. Inspect every changed camera/layout before applying a
single crop to the whole lecture. Cancel/retry are independent of extraction/download state.
Successful older output remains available while reprocessing or after failure.

Processing uses headless OpenCV, NumPy and scikit-image locally. It does not use OCR, AI,
inpainting or network image services. Automatic quadrilateral detection is intentionally
strict; uncertain geometry retains the full image. Teacher masks are foreground hypotheses,
not semantic detection or measured accuracy. Annotation variants and uncertain screenshots
are retained. Partial reconstructions are marked incomplete and require review.

Configure `SLIDE_PROCESSING` as JSON containing `SlideConfig` overrides; defaults include
adaptive sampling enabled, five-second additional intervals, at most 40 extra frames per
video, six per candidate segment, five fusion observations and 500 MiB minimum free disk.
`SLIDE_CHANNEL_PROFILES` maps channel **database IDs** (strings) to configurations, e.g.
`{"12":{"crop":{"left":0,"top":0,"right":1,"bottom":0.9}}}`. Profiles and per-request
configuration are validated. Explicit request fields override the profile/server defaults.
`SLIDE_CONCURRENT_LIMIT=1` and `SLIDE_RETRY_ATTEMPTS=3` bound workers and recovery/resource
retries. Configuration is persisted with each job and successful manifest. Complete fields
and defaults are available from `GET /api/v1/videos/slides/config` and the API schema.

| API relative to `/api/v1/videos` | Behavior |
|---|---|
| `POST /{id}/slide-processing` | Queue with optional `configuration` object and `reprocess` boolean |
| `POST /slides/bulk` | Queue `video_ids`, optional configuration; returns started IDs and per-video errors |
| `GET /{id}/slide-processing` | Independent pending/processing/processed/failed/cancelled status, actual counts and progress |
| `POST /{id}/slide-processing/cancel` or `/retry` | Cancel explicitly or retry failed/cancelled work |
| `GET /{id}/slides?page=1&page_size=6` | Generation ID, paginated slide metadata, warnings and source timestamps |
| `GET /{id}/slides/{generation}/{filename}` | Validated, allowlisted original/crop/processed/mask PNG; refresh listing on generation conflict |
| `DELETE /{id}/slide-processing` | Delete only that video's managed processed generations; preserve source and extracted frames |

Successful outputs are stored under `TEMP_DIR/slides/{video_id}/{generation}` (Docker:
`/data/jobs/slides`, in the existing named volume). Images precede the atomic manifest;
a database transaction switches the successful generation pointer only after validation.
Interrupted jobs restart into a fresh generation on recovery; cancelled jobs stay cancelled.
Failed/cancelled intermediates are preserved until explicit processed-output deletion.
Phase 5's cleanup does not touch slide storage. Operate one backend owner.

Independent module usage and measured examples are in [the Phase 6 report](docs/PHASE6_REPORT.md).
The default sample budget is consumed chronologically: it does not cover all later segments.
There is no claim of complete question coverage; slides displayed entirely between primary
samples may be missed. PDF generation and orchestration remain later phases.
