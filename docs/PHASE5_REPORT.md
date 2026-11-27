# Phase 5 completion report — Video Frame Extraction

Date: 2026-11-27. Status: **Verified**. Phase 6 has not started.

The original implementation evidence below is retained. The stabilization addendum
records subsequent runtime, cancellation, cleanup and verification improvements.

## 1. Implementation summary

Implemented independently callable interval and explicit-timestamp extraction using local
FFprobe/FFmpeg, lossless PNG at original resolution, requested/actual timestamp metadata,
validated atomic JSON manifests, cancellation and bounded subprocess cleanup. Default
sampling is every 60 seconds, with one background job and source retention.

Added independent persistent extraction state, asynchronous individual/bulk API operations,
progress, metadata pagination, original-resolution previews, cancel/retry and safe deletion.
The Videos page exposes these operations, configured intervals, actual counts, progress,
confirmation and reusable lazy/paginated preview. Existing download and overall processing
state contracts remain independent.

No smartboard detection, cropping, reconstruction, obstruction removal, deduplication,
adaptive algorithms, PDF creation, scheduling, OCR or AI was implemented.

## 2. Files created and modified

Created:

- `backend/app/domain/extraction.py`
- `backend/app/infrastructure/frame_extractor.py`
- `backend/app/repositories/extractions.py`
- `backend/app/services/extraction.py`
- `backend/app/api/extractions.py`
- `backend/migrations/versions/6ca8f2d915ab_frame_extraction.py`
- `backend/scripts/benchmark_extraction.py`
- `backend/tests/test_extraction.py`
- `frontend/src/services/extractions.ts`
- `frontend/src/features/videos/extraction-controls.tsx`
- `frontend/src/features/videos/extraction-controls.test.tsx`
- `frontend/src/features/videos/frame-preview.tsx`
- `frontend/e2e/extraction.spec.ts`
- `docs/PHASE5_REPORT.md`

Modified:

- `backend/app/core/config.py`, `backend/app/core/errors.py`
- `backend/app/infrastructure/storage.py`, `backend/app/infrastructure/models.py`
- `backend/app/services/downloader.py`, `backend/app/main.py`
- `backend/tests/test_foundation.py` (migration assertion includes the new table)
- `backend/pyproject.toml` (include benchmark scripts in strict mypy checks)
- `frontend/src/features/videos/videos-page.tsx`
- `frontend/src/features/videos/videos-page.test.tsx`
- `frontend/e2e/videos.spec.ts` (empty-library case explicitly supplies an empty response,
  so retained Docker history does not invalidate the scenario)
- `.env.example`, `docker-compose.yml`
- `README.md`, `ARCHITECTURE.md`, `PLANS.md`, `CHANGELOG.md`

The repository was entirely untracked at task start. Existing files were preserved in place;
no files were staged, committed or pushed. Runtime videos, frames and benchmark outputs
remain under ignored storage paths or the existing Docker volume.

## 3. Architectural decisions and rationale

- **Infrastructure adapter behind domain contracts:** standalone extraction has no HTTP,
  database, YouTube or frontend dependencies. Existing FFprobe validation is reused.
- **Measured strategy selection:** sparse input seeking avoids repeatedly decoding the
  entire video prefix, decoding only the target GOP for each sample. Sequential decoding
  remains configurable for dense sampling. Both paths are covered by offline tests.
  Large explicit filter expressions fall back to seeking to respect subprocess argument
  limits; excessive frame counts are rejected before metadata allocation.
- **Actual timestamps:** integer source PTS multiplied by the rational stream time base,
  relative to playback origin, rather than rounded `pts_time` log text or requested times.
- **Separate extraction table:** video ID primary key, conditional transactional claims,
  independent status/progress/request intent/interval/counts/paths/times/retry/error fields.
  Alembic manages the schema; download and processing statuses are unchanged.
- **Existing recovery pattern:** bounded executor, persistent intent, throttled progress,
  graceful shutdown, bounded resource-error retries, startup recovery and no automatic
  restart of explicit cancellations. Completed matching manifests are reconciled after
  crashes; incomplete generations remain available and a new generation is extracted.
- **Safe publication:** exclusive generation ownership, millisecond filename collision
  rejection, source identity checks, PNG signature/chunk CRC/zlib validation and atomic
  manifest replacement. Existing successful generations are never overwritten.
- **Conflicting operations:** a shared reentrant media-operation lock encloses download
  start/deletion and extraction state changes in the supported single-owner deployment.
- **UI:** centralized fetch/Zod validation and TanStack Query; poll only requested jobs;
  12 lazy images per preview page with original-resolution links and both timestamps.

Sampling policy: request `start + n * interval < end`; include zero by default and retain
samples in the final partial interval. Select the first available source frame at or after
that request. If no frame exists before the exclusive end, fail safely. Multiple requests
inside a VFR gap may legitimately reference the same actual source timestamp.

## 4. Dependencies added and justification

**None.** Uses existing Python/Pydantic/SQLAlchemy/FastAPI, React/TanStack Query/Zod,
FFmpeg/FFprobe and testing tools. Standard-library PNG validation avoids adding an image
library solely for integrity checks. The benchmark uses the Unix `resource` module.

## 5. Actual automated test results

- `uv run pytest -q`: **171 passed in 15.86 seconds**, including all 125 Phase 1–4 tests
  and 46 Phase 5 cases. Later focused extraction run: **46 passed in 11.75 seconds**.
- Coverage includes both extraction strategies; intervals, fractional integer-PTS accuracy,
  ranges/end boundaries, final partial intervals, explicit timestamps, H.264/VP9/AV1 and
  VFR; original dimensions; missing/corrupt inputs; insufficient disk before/during work;
  cancellation; retries; shutdown/restart recovery; retry exhaustion; cancelled recovery;
  duplicate/conflicting operations; manifest reconciliation/integrity; API persistence,
  pagination/preview; safe deletion and symlink containment; sampling resource limits.
- `npm test`: **35 passed across 5 files**; existing 30 frontend regressions plus 5 new
  extraction/preview tests covering interval selection, real counts/progress, cancellation,
  retry, confirmed deletion, bulk errors and lazy paginated full-resolution links.
- Local `npm run test:e2e`: **10 passed in 3.9 seconds**.
- Docker `E2E_BASE_URL=http://127.0.0.1:8080 npm run test:e2e`: **10 passed in 1.8 seconds**.
  The new browser extraction scenario uses HTTP fixtures to isolate the UI workflow.
  Actual FFmpeg, SQLite and API integration are additionally exercised by backend tests
  and the real Docker lecture verification below.

## 6. Linting, formatting, type checking, build and migrations

Passed:

- `uv run ruff check .`
- `uv run ruff format --check .` — 47 files formatted
- `uv run mypy` — 47 source files, including the benchmark script
- `uv run alembic upgrade head`
- `uv run alembic check` — no new upgrade operations
- `npm run lint`
- `npm run format:check`
- `npm run typecheck`
- `npm run build`
- `docker compose config --quiet`
- `docker compose exec -T backend alembic check`

Production builds emit pre-existing third-party Zod/Rollup annotation warnings; builds
succeed. All final required checks pass; no failing requirement is concealed.

## 7. Real-world performance measurements

User-authorized source: `https://www.youtube.com/watch?v=vqYNwaqFPJM&t=4657s`.
The full lecture was used; the URL timestamp does not restrict extraction to that segment.

FFprobe verified **5179.0 seconds (86m 19s), 1280×720, AV1, video-only**, source size
**873,172,843 bytes**. Container acquisition initially returned HTTP 403 without a supported
JS runtime; the authorized video downloaded successfully using the host's supported
JavaScript runtime. No access restrictions were bypassed.

| Measurement | Host seeking | Host sequential | Docker recovered seeking |
|---|---:|---:|---:|
| Interval | 60 s | 60 s | 60 s |
| Expected / actual frames | 87 / 87 | 87 / 87 | 87 / 87 |
| Dimensions | 1280×720 | 1280×720 | 1280×720 |
| Elapsed | 35.1457 s wall | 276.3331 s wall | 31.0131 s adapter timing |
| Child-process CPU time | 34.3561 s | 284.1707 s | Not measured separately |
| Average child CPU, one-core basis | 97.75% | 102.84% | Not measured separately |
| Peak child RSS | 43,106,304 bytes | 54,804,480 bytes | Not measured separately |
| PNG storage | 83,258,189 bytes | 83,258,189 bytes | 102,477,104 bytes |
| Max actual minus requested time | 0 s | 0 s | 0 s |

The sequential run's simple input-seek timing baseline took **25.0873 seconds**, excluding
manifest and integrity work. A preliminary ten-frame seek baseline took **3.1927 seconds**.
The complete validated seek adapter is the 35.1457-second measurement above, approximately
7.9× faster than sequential extraction for this lecture. Benchmarks ran on the available
macOS host with concurrent local/container work; these are measurements, not server
throughput guarantees. CPU/RSS above describe child media processes, not total Python/UI
memory. Different FFmpeg/PNG builds produced different compressed sizes while retaining
resolution; neither implementation downscales screenshots.

Actual timestamp extraction in Docker additionally requested **4657.123** and **4660**
seconds and returned **4657.133333333333** and **4660**. An independent FFprobe frame
scan around that segment confirmed the first actual source timestamp. Fractional PTS
precision is separately regression-tested to 1e-12 seconds on a synthetic source.

Visually inspected the source screenshot at **1740 seconds** from both host and Docker.
The board's Bengali/English text, map labels and handwritten annotations are readable at
1280×720. The teacher and video overlays remain present; Phase 5 makes no reconstruction
or obstruction-removal claim. Readability of every screenshot was not manually audited.

## 8. Docker verification results

- `docker compose up --build -d --wait`: backend/frontend built and healthy.
- Authorized lecture registered as video ID 1 and extracted through the actual HTTP API.
- Start: HTTP 202; duplicate extraction: HTTP 409; source deletion during extraction:
  HTTP 409. Cancellation returned `cancelled` with request intent cleared; explicit retry
  returned HTTP 202 and successfully re-enqueued after worker cleanup.
- Restarted backend while actual extraction was active: state recovered automatically,
  with persistent retry count incremented. Subsequent container replacement while still
  active also recovered; final success recorded `retry_count=2`, **87/87** frames and 100%.
- Validated every PNG and manifest, source presence/size, actual timestamps, 12-item frame
  metadata pagination and original-resolution `image/png` responses.
- Saved SHA-256 hashes of the manifest and all **87 PNGs**, recreated the backend with
  the persistent volume, and verified **every hash was identical** afterward.
- Downloaded source remained intact at **873,172,843 bytes**; no extraction cleanup path
  deletes source videos.
- After completion a container snapshot showed **0.24% CPU and 81.93 MiB memory** for
  the backend. This is an idle snapshot, not a measured active-job peak.
- Container browser suite and migration drift check passed. Verification used the
  available Docker/Colima Linux VM; a separate physical Ubuntu host was not tested.

## 9. Acceptance criteria status

| Criterion | Status / evidence |
|---|---|
| Actual 720p video extraction | Passed — authorized 86-minute lecture, host and Docker |
| Default 60 s / configurable interval | Passed — typed settings, UI and interval tests |
| Preserve source resolution | Passed — 1280×720 outputs plus synthetic checks |
| Individual timestamp extraction | Passed — synthetic/VFR tests and actual lecture segment |
| Accurate timestamps / chronology | Passed — integer PTS tests, actual lecture/FFprobe verification |
| Valid atomic manifests | Passed — integrity tests and complete real-output validation |
| Progress and previews | Passed — unit/API/browser tests and Docker preview responses |
| Cancellation / retries / recovery | Passed — live cancel/retry/restart and offline failure tests |
| No cancelled automatic restart | Passed — fresh-app persistence/recovery regression tests |
| Duplicate prevention / conflicting operations | Passed — API tests and actual HTTP 409 responses |
| Persistence across container recreation | Passed — manifest and all 87 image hashes unchanged |
| Source retained | Passed — real source retained, offline deletion/failure checks |
| Required quality checks / regressions | Passed — results above |

## 10. Known issues and limitations

- Run one backend owner/process, as in Phase 4. The operation lock and recovery executor
  do not provide coordination among independently deployed backend workers.
- Incomplete generations are preserved and restarted rather than incrementally resumed.
  Completed valid generations are reused after publication/DB-update crashes. The
  stabilization retention service now removes expired abandoned intermediates while
  preserving active/recoverable/successful generations and the newest failed attempt.
  Explicit Delete frames clears video-owned generations without touching the source.
- Only PNG output is implemented. Rotated/anamorphic or unusual media beyond the tested
  lecture/synthetic codecs have not had a separate visual audit. General readability is
  constrained by source quality; no processing algorithm improves hidden or blurry text.
- Stabilization makes initial FFprobe validation cancellation-aware with 100 ms polling.
  Both FFprobe and FFmpeg use shared process-group termination, escalating to forced
  termination after a five-second grace period. Their processes are reaped.
- Benchmark comparisons cover one authorized lecture and offline fixtures. A dedicated
  Ubuntu homelab benchmark and inspection of every real screenshot remain unverified;
  no universal resource or readability guarantee is claimed.
- Explicit timestamp sampling is available through the standalone module. The Phase 5
  HTTP/UI interface intentionally requests fixed intervals; adaptive sampling is Phase 6.
- No final automated check is failing. Optional deployment/hardware/visual-audit limits
  above do not represent additional completed capabilities.

## 11. Pending work

No assigned Phase 5 implementation remains pending. Source media, validated outputs and
recoverable intermediates were retained. No commit or push was performed.

**Stop here. Phase 6 requires explicit user approval.**

## 12. Stabilization addendum — 2026-11-27

### Root causes and resolved issues

1. **Docker acquisition gap:** the Python image had neither a supported JavaScript runtime
   nor the separately distributed EJS solver. The earlier host success and Docker 403 were
   consistent with this gap. The [official yt-dlp EJS guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
   requires a runtime plus matching solver scripts. A fresh download now succeeds entirely
   inside Docker; a 403 can still arise from network/access restrictions and is not assumed
   to have one universal cause.
2. **Unbounded intermediate retention:** every failed/cancelled/restarted extraction left a
   generation with no automatic classification or expiry. A reusable cleanup service now
   implements conservative retention at startup and after extraction completion.
3. **Probe cancellation delay:** initial FFprobe used blocking `subprocess.run`. It now uses
   polled communication and shared FFmpeg/FFprobe process-group termination/reaping.
4. **Publication race:** cancellation/shutdown arriving as download validation completed
   could be overwritten by success. Cancellation and verified publication are now serialized
   under the owner lock, with stop checks immediately before committing success.
5. **Recovery cost:** incomplete generations have no reliable per-frame checkpoint for
   source identity/configuration/PTS. Restart-based recovery is retained deliberately;
   validated complete manifests are reused and mismatched/corrupt/incomplete output rejected.
6. **Final-copy storage:** disk reserve was checked during decode but not each final PNG
   copy. Copy/validation now checks disk reserve and cancellation; quota/space failures have
   actionable errors. Progress writes remain throttled; no cleanup writes are added.

### Implementation, architecture and dependencies

Created:

- `backend/app/infrastructure/processes.py`
- `backend/app/services/storage_cleanup.py`
- `backend/tests/test_stabilization.py`

Modified for stabilization:

- `backend/Dockerfile`, `backend/pyproject.toml`, `backend/uv.lock`
- `backend/app/core/config.py`, `backend/app/domain/downloads.py`
- `backend/app/infrastructure/{media_probe,frame_extractor,ytdlp_downloader}.py`
- `backend/app/repositories/extractions.py`
- `backend/app/services/{downloader,extraction}.py`, `backend/app/main.py`
- `backend/tests/{test_downloader,test_extraction}.py`
- `.github/workflows/ci.yml`, `docker-compose.yml`, `.env.example`
- `README.md`, `ARCHITECTURE.md`, `PLANS.md`, `CHANGELOG.md`, `docs/PHASE5_REPORT.md`

Dependencies added: **Deno 2.5.6**, runtime binary copied from the official image pinned to
multi-platform digest `sha256:2f5f9d651af33c337767c423a340f76df35e35ff8ff4734210237b9c6fed94c7`,
and **yt-dlp-ejs==0.8.0**, the exact solver version required by locked yt-dlp 2026.11.23.
No other application dependencies were added. Remote solver downloads are disabled.
The image build executes Deno and imports EJS as UID 10001. Runtime options are passed
explicitly through `DOWNLOAD_JS_RUNTIME` and `DOWNLOAD_JS_RUNTIME_PATH`.

The modular monolith, single backend owner, HTTP schemas, SQLite schema, PNG format and
sparse seeking remain unchanged. Cleanup receives state/active callbacks and the same
reentrant media lock as claims/deletion. It opens all directory components without following
symlinks, uses directory-relative operations, recognizes only numeric video IDs/UUID
extraction generations and known intermediate filenames, and streams per-file accounting.
Unknown content is preserved. State is read once per video; no database writes are needed.

`CLEANUP_RETENTION_HOURS=48` and `CLEANUP_DRY_RUN=false` are validated settings. Requested,
active and shutdown-recoverable jobs are protected; every published manifest, referenced
output, newest failed incomplete attempt and all source videos are retained. Expired older
attempts/cancelled/orphan intermediates are removable. Dry-run reports predicted counts;
applied cleanup reports actual unlinked file counts/logical bytes and errors. Physical disk
allocation may differ from logical byte counts. No scheduler was introduced.

Incremental partial reuse would require a new source/configuration/PTS checkpoint protocol
for both decode strategies and an additional atomicity/integrity contract. That complexity
is disproportionate to the roughly 24–30 seconds of repeated work measured here. Correctness
therefore takes priority: a fresh isolated generation is decoded after an incomplete run.

### Actual automated verification

- Backend: **207 passed in 20.98 s** (all 171 original Phase 1–5 cases retained; 36 new cases).
  Additional assertions cover cleanup after completion in the existing extraction API tests.
- New coverage includes dry-run, retention, active/queued/success/recoverable/referenced
  protection, unknown/source files, root/ancestor/video/generation/frame symlinks, traversal,
  lock serialization, parallel cleanup, startup/completion hooks, probe cancellation,
  shutdown and timeout, forced kill, child-process termination, sanitized acquisition
  errors, runtime options and rejected recovery candidates. Download probe-completion
  cancellation/shutdown cannot publish success.
- Ruff lint and formatting: **passed**, 50 Python files formatted.
- Strict mypy: **passed**, 50 source files.
- Frontend Vitest: **35 passed across 5 files**; ESLint, Prettier, TypeScript and Vite
  production build **passed**. The existing third-party Zod annotation warnings remain.
- Local Playwright: **10 passed in 4.0 s**. Docker Playwright: **10 passed in 2.1 s** on the final rebuilt deployment.
  One sandboxed Docker-browser attempt could not launch Chromium (macOS Mach permission
  error); rerunning with required browser permissions passed. Browser extraction scenarios
  use HTTP fixtures; real processing is verified separately below.
- Fresh isolated SQLite `alembic upgrade head` and `alembic check`: **passed**.
- Compose configuration and container `alembic check`: **passed**, no schema drift.
- ARM64 production image build, non-root Deno evaluation and EJS import: **passed**.
  The official pinned Deno manifest advertises both Linux AMD64 and ARM64.
- An isolated AMD64 backend build was attempted. It stopped at the first Debian shell
  command with `exec format error`: this ARM64 Colima VM has no x86 emulation. No AMD64
  execution pass is claimed. Native AMD64/ARM64 integration CI runners are configured;
  hosted CI has not been executed during this task.

### Real Docker workflow and measurements

Representative source remains the previously authorized full lecture:
`https://www.youtube.com/watch?v=vqYNwaqFPJM`. No credentials, cookies, host JavaScript
runtime, host-downloaded source or access-control bypass was used for this fresh download.
The prior source and successful generation were retained separately.

| Measurement | Actual result |
|---|---:|
| Fresh Docker download + initial FFprobe wall time | 246.1406 s |
| Downloaded source bytes | 873,172,843 |
| Source duration / resolution / codec / audio | 5,179 s / 1280×720 / AV1 / none |
| Recovered extraction manifest processing duration | 23.4195 s |
| Recovered job start-to-completion timestamps | approximately 25.03 s |
| Separate complete validated seek benchmark wall time | 24.1225 s |
| Benchmark child CPU time | 22.4906 s |
| Average child CPU, one-core basis | 93.2350% |
| Peak child RSS | 73,404,416 bytes |
| Peak benchmark Python RSS | 36,421,632 bytes |
| Sampling interval / expected and actual frames | 60 s / 87 and 87 |
| PNG storage | 102,477,104 bytes |
| Maximum actual minus requested timestamp | 0 s |
| Expired verification cleanup | 2 generations / 38 files |
| Logical bytes removed by cleanup | 42,084,610 |

The download completed and FFprobe passed, then the ad-hoc measurement script attempted
Pydantic serialization on a dataclass and raised `AttributeError`. The reporting step was
corrected using dataclass serialization and an independent FFprobe validation passed again.
The 246.1406-second measurement includes download and initial validation; the reporting
error did not mean acquisition failed. Runtime evidence is retained in the Docker volume
under `/data/stabilization-*.json`; these generated artifacts are not repository files.

The benchmark ran separately from active backend extraction. It includes PNG and manifest
integrity checks; child RSS describes media subprocesses, not total application memory.
Additional Docker snapshots were **10.20% CPU / 141.1 MiB** during acquisition and
**99.58% CPU / 100.9 MiB** during recovered extraction. These snapshots are not peaks.
Measurements use the available ARM64 Colima VM and do not establish physical Ubuntu or
cross-architecture throughput guarantees.

Live operations:

1. Downloaded the complete lecture using `YtDlpVideoDownloader` inside Docker into a
   separate verification subdirectory. Independent FFprobe confirmed video-only 720p.
2. Selected that verified source for the existing lecture record, preserving the old
   source and saving its prior extraction state plus 88 original frame/manifest hashes.
3. HTTP extraction returned 202; cancellation after eight reported frames returned
   `cancelled`, cleared requested intent, and explicit retry returned 202.
4. Restarted the backend while retry extraction was active after nine reported frames.
   Startup recovered requested intent, incremented retry count to 1 and completed 87/87
   frames. Every PNG passed CRC/decompression/dimension checks; timestamps were exactly
   `0, 60, …, 5160`. All 88 original successful-generation hashes remained identical.
5. A separate standalone complete extraction produced the benchmark values above.
6. Aged only the two new cancelled/interrupted verification generations beyond 48 hours.
   Recreated the backend with dry-run enabled: logs reported two generations, 38 files,
   42,084,610 bytes and zero errors; every candidate stayed present.
7. Recreated both containers with normal cleanup enabled: startup removed those same
   candidates and reported matching counts/bytes with zero errors. All **182 tracked
   successful files** matched SHA-256 afterward; both source videos remained intact at
   873,172,843 bytes each. `/proc` inspection found no orphan FFmpeg/FFprobe processes.
8. The application remains deployed with dry-run disabled and the persistent volume.

### Acceptance status, limitations and pending work

| Assigned criterion | Status |
|---|---|
| Docker-only authorized 720p video-only acquisition / FFprobe | Passed |
| No host JS dependency / non-root execution / locked solver | Passed |
| Supported runtime for ARM64 and AMD64 | ARM64 executed; both manifests available; native AMD64 execution unverified locally |
| Download cancellation, retries and recovery regression | Passed; probe-completion cancellation/shutdown tests added |
| Cleanup classification, dry-run, retention, counts and safety | Passed; automated coverage and actual Docker startup cleanup |
| Active, successful, recoverable and source protection | Passed |
| FFprobe cancellation, timeout, termination and shutdown recovery | Passed |
| Extraction recovery and integrity | Passed; restart strategy intentionally retained |
| Disk checks / bounded resources / sparse performance | Passed within documented measurements and limits |
| Local and Docker Playwright / prior-phase regressions | Passed |
| Lint, formatting, types, migrations and production builds | Passed on available host/ARM64 Docker |
| Recreation persistence | Passed; 182 successful hashes and both sources retained |
| Physical Ubuntu homelab benchmark | Deferred to Phase 10; hardware unavailable |

Known limits: one backend owner is required; successful/unknown/newest-failed generations
can retain storage indefinitely by design; standalone custom output directories are not
automatically cleaned; source identity uses path/size/mtime, not a full-video cryptographic
fingerprint; YouTube access can still change with upstream behavior or network restrictions.
The cleanup byte metric is logical data removed, not guaranteed physical blocks reclaimed.
Cleanup is synchronous under the operation lock, so a very large accumulated directory tree
can briefly delay new claims. Incomplete extraction restarts deliberately.

Implementation and verification on the available platform are complete. The remaining
verification limits are native AMD64 execution/hosted CI and the optional physical Ubuntu
benchmark; neither is represented as passed. No Phase 6 work, commit or push was performed.
**Stop here; Phase 6 requires explicit user approval.**
