# Phase 3 Completion Report — YouTube Video Discovery

Date: 2026-11-27

## 1. Implementation summary

Implemented and stabilized the Phase 3 YouTube video discovery module using the official YouTube Data API v3, SQLite persistence via SQLAlchemy and Alembic, REST endpoints in FastAPI, and the Videos page in the React frontend:

- **YouTube Data API v3 client** (`YouTubeApiClient`): lightweight `httpx`-based client supporting channel resolution (`/channel/UC...`, `/@handle`, `/user/name`, `/c/name`), paginated keyword search (`search.list`), batched video detail lookup (`videos.list`, up to 50 IDs per call), bounded exponential backoff retries on `429`/5xx/timeouts, and API key sanitization across `__repr__`, logs (`httpx`/`httpcore` INFO silenced), and exception messages.
- **Official Quota Tracking**: aligned with `https://developers.google.com/youtube/data/determine_quota_cost` — tracks `search.list` in its own dedicated daily bucket (`DISCOVERY_SEARCH_QUOTA_LIMIT`, default `100` calls/day) separately from the general read pool (`DISCOVERY_QUOTA_LIMIT`, default `10000` units/day), accounts for pagination and retry HTTP responses, and resets/reports resets in `America/Los_Angeles` midnight Pacific Time (`next_quota_reset_utc`).
- **Video persistence**: `VideoRecord` SQLAlchemy model (`videos` table) with unique `youtube_video_id`, nullable `channel_id` foreign key (`ON DELETE SET NULL` to preserve video history if a channel is deleted), and Alembic migration `f4fbd26e2e58_create_videos_table.py`.
- **Discovery service** (`DiscoveryService`): resolves and caches canonical channel IDs, detects and rejects duplicate canonical channel IDs (`DuplicateChannelError`) on resolution, skips inactive channels, searches using per-channel `search_keyword` (falling back to `DEFAULT_SEARCH_KEYWORD`), applies a configurable UTC lookback window (default 7 days), verifies channel ownership (even for newly resolved channels), defers `upcoming` and `live` livestreams while resolving completed livestreams (`liveStreamingDetails` populated) as `LivestreamStatus.COMPLETED`, accepts all videos strictly longer than 1,200 seconds (`duration_seconds > 1200`), prevents duplicate video records without resetting existing `processing_status`, stops gracefully on quota exhaustion, and uses an in-process thread lock to prevent overlapping discovery runs.
- **Backend API**: `/api/v1/videos` (paginated/filtered/sorted list), `/api/v1/videos/summary`, `/api/v1/videos/{video_id}`, `/api/v1/discovery/run`, and `/api/v1/discovery/channel/{channel_id}` with structured error mapping (`409`, `422`, `503`).
- **Frontend Videos page**: summary cards (total, pending, discovered today, latest run in `Asia/Kolkata`), video table with thumbnails, channel name column, formatted duration, IST timestamps, processing status badges, external YouTube links, channel dropdown filter, publication date range filters (`Published from` / `Published to` in IST boundaries), processing status filter, title search, sorting, pagination, global "Discover Videos" button, and individual "Discover \<Channel\>" action when a channel is selected.

## 2. Files created and modified

### Created
- `backend/app/domain/videos.py`
- `backend/app/infrastructure/youtube_client.py`
- `backend/app/repositories/videos.py`
- `backend/app/services/discovery.py`
- `backend/app/api/videos.py`
- `backend/migrations/versions/f4fbd26e2e58_create_videos_table.py`
- `backend/tests/test_discovery.py`
- `frontend/src/services/videos.ts`
- `frontend/src/features/videos/videos-page.tsx`
- `frontend/src/features/videos/videos-page.test.tsx`
- `frontend/e2e/videos.spec.ts`
- `docs/PHASE3_REPORT.md`

### Modified
- `backend/pyproject.toml` and `backend/uv.lock`
- `backend/app/core/config.py`
- `backend/app/core/errors.py`
- `backend/app/core/logging.py`
- `backend/app/infrastructure/models.py`
- `backend/app/main.py`
- `backend/tests/test_foundation.py`
- `frontend/src/app.tsx`
- `frontend/src/app.test.tsx`
- `frontend/e2e/foundation.spec.ts`
- `docker-compose.yml` (passed `YOUTUBE_API_KEY` and `DISCOVERY_*` environment variables to `backend` service)
- `.env.example`
- `README.md`
- `ARCHITECTURE.md`
- `PLANS.md`
- `CHANGELOG.md`

## 3. Architectural decisions

- **Lightweight HTTP client over Google SDK**: Chose `httpx` instead of `google-api-python-client` to keep dependencies minimal and keep HTTP mocking/testing straightforward.
- **Separate `search.list` quota bucket**: Modeled `search.list` (`DISCOVERY_SEARCH_QUOTA_LIMIT=100`) separately from the general pool (`DISCOVERY_QUOTA_LIMIT=10000`) with `America/Los_Angeles` midnight reset tracking, matching current Google YouTube Data API v3 quota documentation.
- **Nullable `channel_id` FK (`ON DELETE SET NULL`)**: Prevents accidental cascade deletion of video processing history if a channel is deleted.
- **In-process discovery lock**: Prevents overlapping manual discovery runs in the single-process modular monolith (`DiscoveryAlreadyRunningError` mapped to HTTP 409). Persistent cross-process run locking belongs to Phase 8.
- **Strict >1,200s duration filter**: Default `DISCOVERY_MIN_DURATION_SECONDS=1200` with `duration_seconds <= threshold` rejection ensures `1200s` (20m 0s) is rejected and `1201s+` is accepted.

## 4. Dependencies added and their justification

- `httpx==0.29.0` (with `httpcore==1.0.9`, `certifi==2026.11.20`): lightweight typed HTTP client for YouTube Data API v3 calls, timeouts, and retry handling.
- `isodate==0.7.2`: standard ISO 8601 duration parser for YouTube `contentDetails.duration` strings (e.g., `PT1H23M45S`).

## 5. Tests executed and actual results

- **Backend Pytest** (`cd backend && uv run pytest`): **108 passed in 1.19s** (`test_channels.py`: 29, `test_discovery.py`: 59, `test_foundation.py`: 20). All YouTube API calls are mocked; no live network requests were made.
- **Alembic** (`cd backend && uv run alembic upgrade head && uv run alembic check`): exited 0 (`No new upgrade operations detected.`).
- **Frontend Vitest** (`cd frontend && npm test`): **26 passed across 4 test files** (`api.test.ts`: 6, `app.test.tsx`: 5, `channels-page.test.tsx`: 5, `videos-page.test.tsx`: 10).
- **Playwright E2E (local)** (`cd frontend && npm run test:e2e`): **9 passed in 3.5s** across `foundation.spec.ts`, `channels.spec.ts`, and `videos.spec.ts` against local Vite + FastAPI servers.
- **Playwright E2E (Docker)** (`cd frontend && E2E_BASE_URL=http://127.0.0.1:8080 npm run test:e2e`): **9 passed in 1.7s** against rebuilt Docker Compose containers.
- **Docker Compose rebuild & persistence**: `docker compose up --build --wait` succeeded (both containers healthy); `docker compose exec backend uv run --frozen --no-dev alembic check` clean; inserted test video `persistTest01`, ran `docker compose up --force-recreate --wait`, verified `persistTest01` persisted via `GET http://127.0.0.1:8080/api/v1/videos`, and cleaned up test row.

## 6. Linting and type-checking results

- `cd backend && uv run ruff format --check .`: **passed** (32 files already formatted).
- `cd backend && uv run ruff check .`: **passed** (All checks passed).
- `cd backend && uv run mypy`: **passed** (Success: no issues found in 32 source files).
- `cd frontend && npm run format:check`: **passed** (All matched files use Prettier code style).
- `cd frontend && npm run lint`: **passed** (`eslint .`, 0 errors/warnings).
- `cd frontend && npm run typecheck`: **passed** (`tsc -b`, 0 errors).
- `cd frontend && npm run build`: **passed** (`tsc -b && vite build`).

## 7. Acceptance criteria status

1. Channel dropdown filter on Videos page: **Passed** (Vitest + Playwright E2E).
2. Individual channel discovery actions: **Passed** (Vitest + backend API tests).
3. Publication date filtering: **Passed** (Vitest + backend repository tests).
4. Minimum duration filtering accepts strictly > 1,200 seconds: **Passed** (regression test for 1200s rejected / 1201s accepted).
5. YouTube API quota tracking per current official docs (separate `search.list` bucket, configurable limits, `America/Los_Angeles` reset, pagination & retries counted): **Passed**.
6. Deferred livestream rediscovery: **Passed** (multi-run regression test).
7. Duplicate prevention across repeated discovery runs: **Passed** (regression test).
8. Canonical channel ID resolution and duplicate channel handling: **Passed** (regression test).
9. API key never in logs, exceptions, or frontend responses: **Passed** (security regression test + `httpx`/`httpcore` logging guard).
10. Docker Compose rebuilt and started: **Passed**.
11. Playwright tests executed against Docker: **Passed** (9/9).
12. Video persistence across container recreation: **Passed**.
13. Live YouTube Data API v3 verification: **Passed** (executed against live Docker Compose stack with configured `YOUTUBE_API_KEY`).

### Live YouTube API Acceptance Test Results (2026-11-27)

- **Environment fix**: Updated `docker-compose.yml` to pass `YOUTUBE_API_KEY` and `DISCOVERY_*` settings into the `backend` container; verified `Settings()` loads the key masked (`youtube_api_key='***'`).
- **Two active channels registered**:
  - `freeCodeCamp.org` (`https://www.youtube.com/@freecodecamp`, keyword `Course`, `is_active=True`)
  - `CS50` (`https://www.youtube.com/@cs50`, keyword `Lecture`, `is_active=True`)
- **Run 1 (`POST /api/v1/discovery/run`)**:
  - Resolved and persisted canonical YouTube channel IDs: `UC8butISFwT-Wl7EV0hUK0BQ` (`freeCodeCamp.org`) and `UCcabW7890RKJzL968QWEykA` (`CS50`).
  - Checked `2` channels, found `1` qualifying video (`rCx4SCd4N-s`, `"Microsoft Azure AI Fundamentals (AI-901) Certification Course"`, duration `16994s`, published `2026-11-24T15:35:26Z`, `livestream_status=none`, `processing_status=pending`), `0` failed channels, `0` errors.
  - Quota consumed: `api_requests_made=5` (2 `channels.list` + 2 `search.list` + 1 `videos.list`), `search_requests_made=2`, `quota_reset_at=2026-11-27T08:00:00Z`.
- **Run 2 (`POST /api/v1/discovery/run`) — duplicate prevention & ID caching**:
  - Checked `2` channels, `new_videos_added=0`, `existing_videos_skipped=1`.
  - Quota consumed: `api_requests_made=3` (0 `channels.list` lookups because canonical IDs were cached), `search_requests_made=2`.
- **Run 3 (`POST /api/v1/discovery/channel/1`) — individual channel discovery**:
  - Checked `1` channel, `new_videos_added=0`, `existing_videos_skipped=1`, `api_requests_made=2`, `search_requests_made=1`.
- **Filtering verified**: `channel_id=1` returned `1`, `channel_id=2` returned `0`; `published_after=2026-11-24T00:00:00Z` returned `1`, `published_before=2026-11-20T00:00:00Z` returned `0`.
- **Frontend verification**: Headless Chromium at `http://127.0.0.1:8080/videos` confirmed the discovered video title, channel name (`freeCodeCamp.org`), formatted duration (`4h 43m`), `pending` status badge, and summary counts (`Total videos: 1`, `Pending: 1`, `Discovered today: 1`, IST timestamp `27 Nov 2026, 08:36 am`) rendered properly.
- **Security verification**: Confirmed `YOUTUBE_API_KEY` did not appear in API JSON responses or `docker compose logs backend` (90 lines checked).
- **Cleanup**: Removed temporary test channels and video from the Docker database after verification.

## 8. Known issues and limitations

- **Completed livestream live sample**: Neither of the two live test channels had a completed livestream matching the search keyword within the 7-day lookback window during the live test run; completed livestream handling remains verified via multi-run automated tests with mocked `liveStreamingDetails`.
- **Quota persistence scope**: In-memory quota counters reset on `America/Los_Angeles` midnight rollover or process restart; persistent cross-restart quota accounting is deferred until Phase 8 scheduling.
- **Synchronous discovery**: Discovery runs within the HTTP request lifecycle until Phase 8 moves execution to the background worker.

## 9. Pending work

- Phase 4: Video acquisition (`yt-dlp` adapter and local video input, up to 720p video-only).
