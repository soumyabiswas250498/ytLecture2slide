# Requirements — ytLecture2slide

Status: Proposed baseline for implementation. Changes to approved scope require user approval. AGENTS.md governs engineering conduct; this document governs product behavior.

## 1. Objective and boundaries

Create a reusable self-hosted application to convert educational lecture videos into chronological slide PDFs. The first use case is WBPSC IDO. No continuous channel monitoring; discovery occurs only during a daily batch or a manual run. No transcription, audio analysis, OCR, LLM, paid AI API, MCQ generation or SolveMCQ import in scope.

## 2. Functional requirements

| ID | Requirement |
|---|---|
| FR-01 | Manage channels: list, add, edit, delete or disable; import CSV with channel_name, channel_url and sample_video_url. Preserve incomplete entries for review rather than invent channel IDs. Resolve and verify canonical channel identity before discovery. |
| FR-02 | Configure search keyword (initially IDO), search window, minimum duration, schedule, resolution, screenshot interval and processing thresholds. Persist settings. |
| FR-03 | At 03:00 IST daily, or on Run Now, search enabled channels for relevant videos using channel name + keyword and a rolling seven-day window. Use official YouTube metadata where available. Verify channel ID, duration strictly over 20 minutes and completed status; skip upcoming/ongoing streams. Reconsider them on later runs. |
| FR-04 | Record video IDs persistently. Do not enqueue duplicate jobs or reprocess successful videos automatically. Allow failed-job retry and explicit reprocessing. |
| FR-05 | Acquire authorized video-only files using a replaceable acquisition adapter, targeting 720p, falling back to a lower available resolution with a visible warning; no audio or captions. Store media temporarily. Support authorized local video input independently of YouTube. |
| FR-06 | Extract timestamped PNG frames with FFmpeg at configurable 60-second intervals, without downscaling. Preserve source time order. |
| FR-07 | Process the complete original video frame without automatic or manual smartboard cropping or perspective correction, preserving original dimensions and aspect ratio. |
| FR-08 | Group candidate frames from the same slide; use temporal median or foreground-masked fusion to reduce teacher obstruction. Sample additional frames at five-second intervals in relevant segments when needed. Never merge across known slide boundaries or hallucinate permanently hidden text. |
| FR-09 | Use conservative similarity-based deduplication (SSIM/perceptual hashing and suitable supporting evidence). Retain uncertain or materially changed slides, including annotations that may convey answers. Preserve chronology. |
| FR-10 | Generate one PDF per video, one selected slide/frame per page, with video timestamp and source identification. Preserve captured resolution and aspect ratio with `compact` (JPEG quality 85) default, or `lossless`/`maximum_quality`/`high_quality`. If reconstruction is uncertain, include original usable frames instead. (Implemented and stabilized in Phase 7.) |
| FR-11 | Validate the PDF (readable, expected page count, nonempty, slide-generation match) before atomic publication and automatic intermediate cleanup. Remove job-owned temporary video/images only after validation; mark intermediates as `cleaned` while preserving PDFs, metadata, and logs. Preserve recoverable intermediates on failure. (Implemented in Phase 8.) |
| FR-12 | Dashboard: show discovered, queued, running, successful, failed and skipped videos; per-job stage and honest measurable progress, logs and actionable errors. |
| FR-13 | PDF library: filter by date/channel, preview, download individually, and download selected PDFs as ZIP. |
| FR-14 | Persist jobs and history across restarts. Recover interrupted jobs, support bounded retries and prevent overlapping batch execution. |

## 3. Default configuration

| Setting | Default |
|---|---|
| Schedule | Daily 03:00, Asia/Kolkata (editable; earlier 23:00 was also discussed) |
| Search window | Rolling seven days |
| Keyword | IDO |
| Minimum duration | Strictly greater than 20 minutes |
| Target maximum resolution | 720p |
| Primary sample interval | 60 seconds |
| Adaptive sample interval | 5 seconds |
| Image format | PNG |
| Smartboard crop, obstruction removal, deduplication | Enabled, with safe fallback |
| PDF images | Lossless, original extracted resolution |
| Video concurrency | 1 |
| AI usage | None |

## 4. Non-functional requirements

- NFR-01: Modular monolith; reusable typed processing services, no hardcoded exam or channel names.
- NFR-02: Local video/image processing; YouTube metadata and permitted media acquisition are external network operations.
- NFR-03: Persistent state, atomic outputs, safe path handling and bounded resource consumption.
- NFR-04: Clear stage progress; never claim a result when processing or verification failed.
- NFR-05: Testable modules with offline fixtures; no dependence on live YouTube services for routine CI.
- NFR-06: Strict TypeScript, typed Python, validation, logging, linting, tests and documentation per AGENTS.md.
- NFR-07: Secrets remain server-side; protect access if exposed outside a trusted network. Do not publicly expose an unauthenticated service.
- NFR-08: Respect service terms and content permissions; do not bypass access controls.

## 5. Acceptance scenarios

- Import the channel CSV twice: no duplicate canonical channels; unresolved rows are reported.
- Discover the same eligible video in two runs: one active job; previously successful video is skipped.
- A live video is skipped today and can be found after completion in a later run.
- A synthetic two-hour video yields approximately 120 primary frames, depending on start/end sampling policy; the exact policy is documented and tested.
- A teacher moves across a fixed slide: reconstruction is evaluated against unobstructed ground truth where available; permanently obscured text is never represented as recovered.
- Two visually similar but distinct questions are retained by the conservative deduplication policy.
- Failed or corrupt PDF output does not cause premature deletion of source media.
- Restart during processing: the job becomes recoverable without a duplicate successful output.
- The user can preview a valid PDF and download selected PDFs in a ZIP.

## 6. Decisions and limitations

03:00 is the current proposed default from the latest workflow summary, not a fixed requirement. Exact smartboard detection thresholds, crop profiles and quality metrics must be validated against representative authorized lectures in Phase 6. Discovery completeness and 720p readability are not guaranteed. Acquisition availability depends on permissions, service behavior and adapter support. No numerical reconstruction accuracy or throughput target is asserted before benchmarking.
