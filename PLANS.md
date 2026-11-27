# Development plan — ytLecture2slide

Status: Phase 1, Phase 2, Phase 3, and Phase 4 verified; final verification recorded in docs/PHASE1_REPORT.md, docs/PHASE2_REPORT.md, docs/PHASE3_REPORT.md, and docs/PHASE4_REPORT.md. Phase 5 is implemented and verified; Phase 6 implementation and verification are recorded below; Phases 7–10 are not started. Execute one phase at a time through Codex. Read AGENTS.md, REQUIREMENTS.md and ARCHITECTURE.md before changes. Do not start the next phase without approval. Update this plan and CHANGELOG.md with actual outcomes, not anticipated results.

## Phase 1 — Foundation

- Status: **Verified (2026-11-26)**. Backend 20 tests, frontend 11 tests, local and Docker browser suites 2 tests each, quality/build/migration checks and Docker persistence passed. See docs/PHASE1_REPORT.md for evidence. Phase 2 remains not started.

- Scope: initialize repository, Python/FastAPI and React/TypeScript/Vite foundations, typed configuration, basic health endpoint, Docker Compose development setup, quality tooling, test harnesses and CI. Establish SQLite migration approach and documentation. Install only dependencies necessary for this phase.
- Acceptance: backend and frontend start; health endpoint works; sample tests, linting and type checks pass; Docker configuration is validated and smoke-tested where available; actual setup commands are documented. No channel CRUD, video acquisition or processing implementation.

## Phase 2 — Channel management

- Status: **Verified (2026-11-27)**. Backend 49 tests (29 new channel tests + 20 Phase 1 tests), frontend 16 tests (5 new channel UI tests + 11 existing tests), local and Docker Playwright suites (3 tests each), linting, type checking, build, Alembic migration checks and Docker container recreation persistence passed. See docs/PHASE2_REPORT.md for evidence. Phase 3 remains not started.

- Scope: SQLite persistence, migrations, channel CRUD, enable/disable, CSV import and validation; channel identity fields and duplicate handling. Reusable frontend channel management UI.
- Acceptance: data survives restart; repeated CSV import is safe; invalid and unresolved rows are reported; CRUD and UI states tested. External canonical identity verification can be completed in Phase 3; never mark guessed IDs verified.

## Phase 3 — Video discovery

- Status: **Verified (2026-11-27)**. Backend 102 tests (53 new discovery/repository/client tests + 49 Phase 1 & 2 tests), frontend 26 tests (10 new Videos page tests + 16 existing tests), local Playwright E2E suite (9 tests), Ruff lint/format, strict mypy (32 files), ESLint, Prettier, strict TypeScript, Vite production build, and Alembic migration checks passed (all YouTube API calls mocked in automated tests; live API verification not executed without live `YOUTUBE_API_KEY`). See docs/PHASE3_REPORT.md for evidence. Phase 4 remains not started.

- Scope: official YouTube Data API adapter, search by channel and configurable keyword, canonical channel checks, seven-day publication window, duration and completed-stream filtering, video history and candidate deduplication. Manual discovery for testing, not continuous monitoring.
- Acceptance: fixtures cover irrelevant, short, wrong-channel, live, completed and duplicate videos; pagination and quota/error handling tested; credentials never exposed. Report actual live-service verification separately if authorized credentials are available.

## Phase 4 — Video acquisition

- Status: **Verified (2026-11-27)**. Backend 123 tests (15 new downloader/FFprobe/API tests + 108 Phase 1–3 tests), frontend 30 tests (4 new download UI tests + 26 existing tests), local and Docker Playwright E2E suites (9 tests each), Ruff lint/format, strict mypy (38 files), ESLint, Prettier, strict TypeScript, Vite production build, Alembic migration checks, live sample video acquisition in Docker (`jNQXAC9IVRw`, `320x240`, `av1`, `223779` bytes, no audio), and container recreation persistence passed. See docs/PHASE4_REPORT.md for evidence. Phase 5 results are recorded below.

- Scope: replaceable yt-dlp acquisition adapter for authorized video, local-video input, up to 720p video-only, temporary storage, progress, timeouts and safe cancellation/error handling.
- Acceptance: authorized fixture/local media works; resolution and audio policy verified; failure does not remove user originals; mocked adapter tests cover network and permission errors. No access-control bypass.

## Phase 5 — Frame extraction

- Status: **Verified (2026-11-27)**. Independent interval/timestamp extraction, original-resolution PNGs, source PTS manifests, persistent jobs, recovery/cancellation/retries, API and paginated UI are implemented. An authorized 5179-second 720p AV1 lecture produced 87 frames. Backend, frontend, local/Docker browser and container persistence evidence is recorded in docs/PHASE5_REPORT.md. Phase 5 stabilization adds Docker-contained JavaScript/EJS support, cancellation-aware FFprobe and conservative intermediate retention; evidence is in the stabilization addendum of the same report. Phase 6 was explicitly authorized and is recorded below.

- Scope: independent FFmpeg module, configurable primary sampling and arbitrary additional timestamps, PNG output and frame metadata.
- Acceptance: short synthetic videos prove interval, ordering and timestamp correctness; no unwanted downscaling; resource/error tests cover missing/corrupt inputs. Document start/end sampling policy.

## Phase 6 — Smartboard processing

- Status: **Verified within documented conservative limits (2026-11-27)**. Backend 241 tests (including opt-in authorized data), frontend 40 tests, local/Docker browser 11 tests each, lint/types/build/migrations and 489-hash Docker persistence passed. The 87-frame lecture produced 86 review candidates with 40 extra samples and one partial fusion. See docs/PHASE6_REPORT.md. No Phase 7 work is authorized.

- Scope: crop and perspective correction, same-slide grouping, teacher obstruction reduction through temporal/masked fusion, adaptive five-second sampling, conservative duplicate detection, quality flags and fallback.
- Acceptance: synthetic fixtures and representative authorized lectures demonstrate behavior; distinct questions and meaningful annotations are retained; uncertain reconstruction falls back to originals; report measured outcomes, failure examples and thresholds. Do not claim permanently hidden text is recovered. User visual review of real examples is required before approval to advance to Phase 7.

## Phase 7 — PDF generation and library

- Scope: reusable image-to-PDF module with source timestamps, one retained image per page, lossless encoding, integrity checks and atomic publication; PDF library preview, filters and individual/bulk ZIP downloads.
- Acceptance: verify page count, image fidelity, chronology, safe paths, valid ZIP contents and failure behavior. Never delete temporary source files before validated output; preserve user-owned local originals.

## Phase 8 — Pipeline, queue and scheduler

- Scope: integrate completed modules; durable run/job state, one worker by default, daily 03:00 Asia/Kolkata schedule, manual run, bounded retries, safe cleanup and interrupted-job recovery. No continuous discovery.
- Acceptance: full local fixture-to-PDF integration; duplicate and overlapping runs prevented; restart and publication-crash recovery tested; schedule/timezone tested; successful job-owned files cleaned only after verified publication.

## Phase 9 — Dashboard and settings

- Scope: dashboard, counts, live stage/progress via polling, logs, job history, settings validation, Run Now and retry controls. Consolidate existing phase-specific UI.
- Acceptance: all relevant settings persist; status and counts reflect actual backend state; failed/skipped reasons displayed; responsive/accessibility checks; no fabricated percentages.

## Phase 10 — Validation and deployment

- Scope: end-to-end test suite, authorized sample batch, benchmark CPU/memory/disk/time, tune conservative thresholds, Docker homelab deployment instructions, backup/restore and operational troubleshooting.
- Acceptance: relevant tests, lint and types pass; production deployment smoke-tested in an available environment or explicitly reported unverified; operational limits documented; user accepts output quality. No throughput promises before measurement.

## Completion protocol for every phase

1. Inspect repository and confirm phase scope against requirements.
2. Implement only the assigned phase; reuse existing code and preserve unrelated changes.
3. Run relevant tests, linters, type checks and available smoke tests.
4. Update changed docs, roadmap status and changelog with factual results.
5. Report implemented files, decisions, dependencies, actual check results, acceptance criteria, known issues and pending work. Stop for approval.

Phase statuses: Not started / In progress / Blocked / Implemented (verification pending) / Verified. Do not mark Verified without evidence. User approval to advance is separate from test status.
