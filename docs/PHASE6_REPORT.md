# Phase 6 completion report — Smartboard processing and reconstruction

Date: 2026-11-27 (Asia/Kolkata). Status: **Implemented and verified within the limits below.**
Scope: Phase 6 only. No commit or push.

## Implementation and architecture

Implemented independent local board isolation/homography, normalized crops and channel
profiles, conservative chronological grouping/deduplication, foreground masks, bounded
adaptive FFmpeg sampling, observed-pixel fusion and temporal-median reconstruction. The
processor preserves all Phase 5 inputs and records a decision for each primary screenshot.

Added a separate SQLite job table with transactional claims, independent status/counts,
bounded workers/resource retries, cancellation, graceful shutdown, startup recovery,
explicit reprocessing and safe processed-output deletion. Successful generations are
immutable; a validated atomic manifest precedes transactional publication. Reprocessing
failure/cancellation preserves the previous successful pointer. Incomplete work restarts in
a fresh generation, following Phase 5's recovery policy.

The Videos page provides individual/bulk processing, actual counts, progress, cancel/retry,
comparison previews, generation-qualified full-resolution image links, and manual crop
coordinates with an image overlay. Fallback/incomplete/manual-review labels and heuristic
measurement labels are explicit. No overall pipeline, scheduler, PDF, OCR, LLM or paid API
was implemented. Existing video and extraction contracts remain independent.

The modular monolith and single backend owner are retained. Image modules have no FastAPI
or database dependency. The processor receives the existing frame-extractor protocol.
The application composes the service/repository/extractor and shared media-operation lock.
No significant stack or architecture change was needed.

## Files created and modified

Created:

- `backend/app/domain/slides.py`
- `backend/app/services/imaging/{__init__,board,similarity,obstruction,reconstruction,pipeline}.py`
- `backend/app/services/slides.py`, `backend/app/repositories/slides.py`, `backend/app/api/slides.py`
- `backend/migrations/versions/ab61c4ea9012_slide_processing.py`
- `backend/scripts/benchmark_slides.py`, `backend/tests/test_slides.py`
- `frontend/src/services/slides.ts`
- `frontend/src/features/videos/{slide-controls,slide-preview}.tsx`
- `frontend/src/features/videos/slide-controls.test.tsx`, `frontend/e2e/slides.spec.ts`
- `docs/PHASE6_REFERENCES.json`, this report.

Modified:

- `backend/app/{main.py,core/config.py,infrastructure/models.py,services/extraction.py}`
- `backend/pyproject.toml`, `backend/uv.lock`, `backend/tests/test_foundation.py`
- `frontend/src/features/videos/videos-page.tsx`
- `.env.example`, `docker-compose.yml`, `.github/workflows/ci.yml`
- `README.md`, `ARCHITECTURE.md`, `PLANS.md`, `CHANGELOG.md`.

Visual artifacts are in ignored `storage/phase6/`. Runtime benchmarks, intermediate
attempts, original media and successful generations stay in the persistent Docker volume.
The repository was entirely untracked at task start; existing unrelated files were retained.

## Dependencies

Added through uv with a refreshed lockfile:

| Direct dependency | Resolved version | Justification |
|---|---|---|
| opencv-python-headless | 4.14.0.94 | Local geometry, masks, features and pixel operations; no GUI dependency in Docker |
| NumPy | 2.5.5 | Bounded image-array operations and temporal statistics |
| scikit-image | 0.26.0 | SSIM supporting evidence |

Transitive numerical/image dependencies are locked in `uv.lock`. No frontend dependency or
ImageHash package was added: a small DCT perceptual hash uses the already required OpenCV.
No external image or AI service is called.

## Algorithm selection and configurable defaults

Representative frames were inspected before finalizing algorithms: the complete 87-frame
contact sheet and full-resolution question, annotation, additional-observation and outro
examples. The board occupies nearly the complete image, with a persistent footer and
teacher foreground. Educational panels inside the PPT must not be mistaken for board edges.

- Automatic crop requires one convex quadrilateral covering at least **85%** of the image,
  with corners within **6%** of frame corners. Otherwise retain full resolution/full frame.
  Perspective uses ordered corners and homography. Explicit normalized crops override this
  decision. The automatic detector fell back on this lecture; explicit crop worked.
- Candidate comparison uses SSIM **0.85**, edge Jaccard **0.60** and changed-pixel fraction
  at most **0.22**, with a **24/255** per-pixel change cutoff. Analysis width is at most
  **640**; exclusion change fractions are measured at original resolution. DCT hash distance
  is supporting descriptive evidence, never a standalone exclusion/grouping rule.
- Shared-template similarity only nominates additional-frame candidates. Different primary
  images remain separate groups unless redundancy is established against both the previous
  original and processed image. No transitive grouping across successive primary changes.
- Exclusion requires SSIM at least **0.99** and changed fraction at most **0.00002** against
  both references. A stricter initial SSIM of 0.998 removed no frames; manually inspecting
  the final static outro supported the revised noise tolerance. Question/annotation variants
  remain retained. The primary source files are never deleted.
- Foreground detection evaluates MOG2, temporal differences/median, color hints, connected
  contours and morphology. Component area range is **1.5–40%**; lower-frame tall components
  receive a padded conservative silhouette (**3%** width padding, **5** pixel dilation).
  These hypotheses can over-mask photographs, artwork or stationary content.
- Alignment first evaluates phase correlation (response at least **0.8**, shift at most
  **2 pixels**) and verifies uncertain cases with ORB matches (distance at most **32**, at
  least **12** matches, **80%** inliers within **1 pixel**). Nonzero rounded translations
  fall back rather than resampling small educational text.
- Fusion requires stable visible content outside masks: residual fraction at most **0.0001**.
  A **3×3** Gaussian comparison suppresses codec/jitter noise; its mask boundary is excluded
  to prevent blur leakage. This smoothing is not applied to published fused pixels.
  At least **two agreeing visible observations** support each replacement. Default fusion
  copies actual source pixels; independently callable temporal median is also tested.
  No inpainting is used. Permanently unseen pixels remain original/uncertified.
- Additional sampling defaults to **5 seconds**, strictly inside the primary-anchor/next-primary
  interval (last interval ends at extraction end), capped at **40/video**, **6/segment**,
  and **5 observations/fusion**. Every additional source PTS is boundary checked and its
  image is independently checked before fusion. A transition at 10 seconds in this video
  was rejected for the opening question. Frames that fail compatibility stay on disk with
  rejection warnings. Search intervals are uncertain candidate intervals, not proven scene cuts.
- Cropped geometry must match before fusion. Additional source path/size/mtime must match
  the Phase 5 extraction manifest, and source identity is checked again before publication.

All similarity/alignment thresholds above are validated configuration fields. Configuration
is supplied by environment JSON, optional channel database-ID profiles and explicit request
fields; request overrides preserve other server/profile defaults. Each claim/manifest stores
its resolved configuration. Default minimum free storage is **500 MiB**, concurrency **1**,
and bounded recovery/resource-error retry limit **3** with exponential backoff.

Least-obstructed original selection was considered: a clear observation at 195 seconds can
be preferable to a partially fused image, but weaker similarity alone cannot verify its
annotation state. Uncertain cases retain their primary original and all sampled files.
The published partial fusion remains explicitly reviewable alongside the original.

## Manual references and visual findings

[Reference observations](PHASE6_REFERENCES.json) record teacher movement, substantial/partial
obstruction, answer ticks, handwriting, similar-template different questions and transitions.
No semantic labels were generated by OCR or an AI algorithm.

Representative artifacts, retained locally rather than committed:

- [All 87 source thumbnails](../storage/phase6/contact-sheet.jpg)
- [Before: 180 seconds](../storage/phase6/before-180.png)
- [After: partial observed-pixel reconstruction](../storage/phase6/after-180.png)
- [Manual crop of annotated 780-second frame](../storage/phase6/crop-780.png)
- [Actual comparison UI](../storage/phase6/ui-comparison.png)
- [Actual crop overlay UI](../storage/phase6/ui-crop.png)

At 180 seconds the teacher obscures portions of options A and C. Additional observations at
185/190/195/200 seconds expose useful pixels. The resulting partial fusion improves option
readability, but leaves clothing/edge artifacts and uncertain fragments: it is **not a clean
or fully verified reconstruction**. All educational pixels come from retained observations.
An opt-in real-data regression compares a manually chosen recovered option-A region against
a visible source; synthetic tests additionally compare reconstruction against exact ground truth.

The explicit crop `(0, 0, 1, 0.865)` produced **1280×623** for the annotated 780-second
example and preserved its four options/tick while excluding most of the footer. This is a
manually inspected example, not a hardcoded channel rule or a claim that automatic cropping
worked on every frame. Default processing kept the full image.

All primary question/annotation frames remained represented; the only excluded screenshot
was the manually verified static **5160-second outro**, redundant with 5100 seconds.
Thus **zero distinct primary question slides were removed in this evaluated dataset**.
This does not establish complete question coverage of the video or accuracy on unseen channels.

## Verification and measured results

Final full backend run: `PHASE6_REAL_DATA=/tmp/phase6-data .venv/bin/pytest -q`:
**241 passed in 24.13 s** (207 prior Phase 1–5 regressions plus 34 Phase 6 cases).
The authorized real-data case is opt-in; without that environment variable routine offline
runs skip that single case. The focused Phase 6 run passed **34 tests in 4.27 s**.

Coverage includes automatic/full-frame/manual board isolation, a real synthetic projective
warp, similar-template distinct questions, annotation variants, moving and stationary
foreground, both reconstruction methods against exact synthetic ground truth, uncertain
alignment/annotation/permanent-obstruction fallback, bounded real FFmpeg sampling and source
PTS, source identity/output-root checks, disk failure, decision/manifest integrity, original
hash retention, job/API processing, preview allowlists/stale generation rejection, explicit
reprocessing failure with previous success preserved, cancellation/conflicting operations,
resource retry, shutdown recovery, retry exhaustion, cancelled recovery and safe deletion.
The existing migration test now expects the additional table and verifies schema agreement.

| Check | Actual result |
|---|---|
| Ruff lint / format check | Passed; 63 Python files |
| Strict mypy | Passed; 63 source/test/script files |
| Frontend Vitest | 40 passed across 6 files |
| ESLint / Prettier / TypeScript / Vite build | Passed |
| Local Playwright | 11 passed in 6.2 s |
| Docker Playwright | 11 passed in 2.2 s |
| ARM64 Docker images / health / Compose configuration | Passed |
| Fresh SQLite upgrade and Alembic drift checks | Passed through regression test |
| Container Alembic check | Passed, no new upgrade operations |
| Docker recreation persistence | 489 file hashes matched, including source video, all primary PNGs/manifest and successful slide/sample outputs |
| Actual UI comparison/crop inspection | Passed, screenshots linked above |

The initial sandboxed Docker-browser/screenshot launches failed at macOS Chromium Mach
port permissions before application execution. Rerunning with browser launch permissions
passed. Vite retains the pre-existing third-party Zod annotation warnings; production builds
succeed. Browser processing scenarios use HTTP fixtures; actual processing is separately
verified by synthetic/backend tests and the real Docker workflow.

### Authorized lecture benchmark

Source: retained `vqYNwaqFPJM`, 5179 seconds, 1280×720, video-only AV1, **873,172,843 bytes**.
No download or external image service was needed. Initial primary collection: **87 PNGs**.
Run on the available ARM64 Colima Docker VM using `benchmark_slides.py`, final release
output retained at `/data/phase6-evaluation-release` and locally in
`storage/phase6/{benchmark,manifest}.json`.

| Measurement | Actual value |
|---|---:|
| Input screenshots | 87 |
| Additional sampled frames | 40 |
| Published candidates | 86 |
| Redundant primaries excluded | 1 (5160-second outro) |
| Distinct primary question states incorrectly excluded | 0 in evaluated dataset |
| Partial fused candidates | 1 |
| Original-image fallbacks | 85 |
| Groups with at least three accepted observations | 4 |
| Of those groups, fusion declined / partially produced | 3 / 1 |
| Groups lacking enough accepted observations | 82 |
| Complete, verified reconstructions | No complete-accuracy claim; 0 certified |
| Candidates requiring manual review | 86 |
| Wall duration | 35.1426 s |
| Python CPU time | 29.8020 s |
| Child process CPU time | 10.3864 s |
| Combined CPU / wall, one-core basis | 114.36% |
| Peak Python RSS | 293,355,520 bytes |
| Child high-water RSS | 293,355,520 bytes |
| Output logical storage, including comparison copies/samples | 351,785,501 bytes |
| All 88 primary PNG/manifest hashes unchanged | True |

RSS high-water values are Unix resource-accounting measurements, not a simultaneous
application/child memory total. Child high-water RSS can include inherited pre-exec process
memory; it is not an isolated FFmpeg peak. CPU sums include child decoding; percentages can
exceed one core. No physical Ubuntu/AMD64 throughput claim is made. The 16-second initial
host baseline used no adaptive sampling and stricter deduplication; it is not a like-for-like
speed comparison.

All 86 results have `fallback=true` because automatic board geometry was uncertain, even
though one used partial pixel fusion. The 180-second group's heuristic suspected obstruction
fraction was **0.1738531** and its unresolved fraction **0.0160341**. These are mask-derived
fractions, not reconstruction accuracy or manually verified coverage percentages.

### Real API cancellation, recovery and persistence

1. Started processing through HTTP; cancelled after three completed primaries and 18 reported
   additional frames. State became cancelled and durable request intent cleared.
2. Explicit retry returned 202. Restarted the backend after three completed primaries/18
   additional frames during that retry. Startup recovered intent with retry count 1.
3. Recovered job completed 87 inputs, 40 additional samples, 86 outputs, one duplicate and
   one partial fusion; review count 86. Original video/PNG hashes were unchanged.
4. Recreated both containers and verified **489 SHA-256 hashes**, the successful publication
   pointer and persisted counts. The source, all original screenshots and successful slide
   images/sample files survived. Container migration check passed.
5. Reprocessed using the final code and verified all contributing frame references in the
   fused slide while preserving the previous successful generation. The application remains
   deployed on the persistent volume.

Independent invocation:

```sh
cd backend
PYTHONPATH=. uv run python scripts/benchmark_slides.py \
  --frames /path/to/extraction-generation \
  --output /path/to/new-slide-generation --video-id 1 \
  --source /path/to/the-same-retained-video \
  --configuration '{"adaptive_enabled":true,"max_additional_samples":40}'
```

The output directory must be new and separate from the original screenshots. Adaptive
source path/size/mtime must match the extraction manifest. The processor and individual
board/comparison/obstruction/reconstruction functions can also be imported independently.

## Acceptance criteria

| Criterion | Status |
|---|---|
| Representative smartboard isolation | Passed with explicit normalized crop; automatic detection conservatively falls back |
| Preserve distinct questions and answer/annotation variants | Passed for evaluated primaries and synthetic regression fixtures |
| Reduce obstruction when observable information exists | Passed for synthetic exact-ground-truth cases and one partial real example; residual artifacts documented |
| Adaptive extraction and boundary/content checks | Passed; 40 real extra frames, transition rejection and synthetic PTS tests |
| Conservative duplicate removal / uncertain review | Passed; one redundant outro excluded, all 86 outputs flagged for review |
| Original screenshots/video intact | Passed; cryptographic integrity checks |
| Progress, previews and crop UI | Passed; actual UI inspection, component and browser tests |
| Cancellation, resource retries and recovery | Passed; automated and live restart/retry checks |
| Docker persistence | Passed; 489 hashes across recreation |
| Real-world evaluation documented | Passed within stated sample/visibility limits |
| Required automated checks | Passed on available host/ARM64 Docker |

## Known issues, limitations and pending work

The evaluated lecture remains conservative: all outputs require manual review, static
foreground cannot be certified unobstructed, and complete hidden-content recovery is not
claimed. Adaptive budget is consumed chronologically in the early segments; most later
slides receive no additional samples with the default cap. The result is a small reduction
in screenshot count, not aggressive conversion to one clean slide per question.

Pixel/SSIM thresholds can miss faint or tiny changes, masks can misclassify artwork, and
same-template semantic identity cannot be proven without interpreting text. Retaining
primary variants and originals limits destructive consequences. Additional samples that
might show another slide are preserved but not silently merged. The API comparison gallery
shows published candidates; rejected extra PNGs remain available in generation sample folders.

All current outputs are marked incomplete/uncertified because heuristic visibility does
not prove complete stationary-region coverage. Obstruction/quality fractions are explicitly
not measured reconstruction accuracy. Complete slides shown only between primary samples
can be missed; increasing a bounded adaptive budget is not a completeness guarantee.

Storage grows because comparison originals/crops/processed images are retained independently,
including old successes and failed/cancelled generations. Explicit processed-output deletion
is available; there is no automatic slide retention scheduler. Use one backend owner. No
physical Ubuntu homelab or native AMD64 performance claim is made from an ARM64 Colima run.

User visual acceptance of these examples remains a product review step. **Stop after Phase 6;
Phase 7 requires explicit approval.** No PDF or later-phase work has started.


---

# Phase 6 Optimization & Stabilization Addendum (2026-11-27)

## 1. Root causes of the original poor results

1. **Automatic smartboard detection failure**: The lecture smartboard fills the upper 86.5% of the frame with a bright promotional footer below, lacking a continuous outer 4-sided bezel contour >= 85% of frame area within 6% of all borders. Consequently, `isolate_board` fell back to full-frame on all 87 frames (`fallback=true`, `review_count=86`).
2. **Global pixel-wise duplicate check**: `compare()` required global `SSIM >= 0.99` and `changed_fraction <= 0.00002` (0.002% of pixels). Any teacher movement or compression difference prevented grouping, resulting in only 1 duplicate removed (`5160s` outro) out of 87 frames.
3. **Single-pass chronological adaptive sampling**: Sampling ran inside the primary frame loop, consuming all 40 extra samples between `5s` and `380s` (first 6.5 minutes of an 86-minute video), leaving the remaining 80 minutes with 0 adaptive samples.
4. **Reconstruction-first & blanket manual review**: Every slide defaulted to `incomplete=True, manual_review=True` regardless of actual visibility, and `pipeline.py` wrote 4 full-resolution PNGs per slide (`original`, `crop`, `slide`, `mask`), producing ~351.8 MB of output.

## 2. Algorithms evaluated

- **Channel-specific persistent crop & layout validation**: Normalized crop + optional 4-point perspective corners stored in SQLite (`channel_board_profiles`), validated via aspect-ratio tolerance (<= 15%), minimum area (>= 30%), non-blank variance, and edge-structure retention (>= 35% of frame edges).
- **Obstruction-aware segmentation (`compare_visible`)**: Joint 2-frame foreground masking (`obstruction_masks([a, b])`), mutually visible SSIM, 4×4 grid cell change inspection, mutually visible edge Jaccard, and new-annotation/bright-stroke detection. Checked against both segment anchor and previous frame to prevent transitive drift.
- **Best-frame selection (`score_candidate` / `select_best_or_reconstruct`)**: Ranks candidates by visible board coverage (`1 - obstruction_fraction`) and visible-region Laplacian variance/contrast, selecting `clear_original` or `improved_original` directly when `obstruction_fraction <= 0.03` before attempting observed-pixel fusion.
- **Whole-video priority-based adaptive sampling**: 3-pass pipeline assessing all primaries first, scaling budget with video duration (`45 samples/hour`, capped at `120`), and distributing samples round-robin across 4 temporal quarters with early stopping once a clear observation is found.
- **Storage optimization**: Reference immutable Phase 5 frames for unmodified originals, skip duplicate crop/slide PNGs when identical, and make diagnostic masks opt-in (`save_diagnostics=False` by default).

## 3. Selected algorithms and justification

All five improvements above were selected and integrated into `board.py`, `similarity.py`, `obstruction.py`, `reconstruction.py`, `pipeline.py`, `services/slides.py`, and `repositories/slides.py`. They preserve every existing reliability, safety, and non-AI constraint while directly fixing each root cause.

## 4. Rejected approaches and reasons

- **Aggressive global SSIM relaxation without grid/annotation checks**: Rejected because it risks merging distinct questions on shared PPT templates or losing small answer ticks/underlines.
- **Mandatory numerical deletion quotas**: Rejected per requirements; accuracy and distinct-question preservation take strict priority.
- **Frame-by-frame full-resolution scanning**: Rejected as disproportionate on CPU-only hardware compared to 60s primary + priority-distributed 5s adaptive sampling.

## 5. Before-and-after benchmark comparisons

Evaluated on the authorized 86-minute WBPSC IDO lecture (`vqYNwaqFPJM`, 5179s, 1280×720 AV1, 87 primary frames):

| Metric | Baseline (Before) | Optimized (After) | Change |
|---|---:|---:|---:|
| Primary screenshots | 87 | 87 | — |
| Additional sampled frames | 40 (all in 0–380s) | 65 (distributed across all 4 quarters) | Whole-video coverage |
| Published slides | 86 | 76 | -10 slides |
| Redundant screenshots excluded | 1 | 11 | **11× improvement** |
| Distinct reference question states lost | 0 | **0** | Preserved 100% |
| Fallback count | 86 | **0** | Channel crop profile applied |
| Clear original selections | 0 | **18** | No unnecessary review/fusion |
| Incomplete / review slides | 86 | 58 | -32.6% manual review |
| Output storage (bytes) | 351,785,501 (~335.5 MiB) | 152,573,530 (~145.5 MiB) | **-56.6% storage** |
| Wall duration | 35.14 s | 37.76 s | +2.6 s (for 65 vs 40 extra samples) |
| Original PNG hashes unchanged | True | True | 100% intact |

## 6. Representative visual examples

Retained locally in `storage/phase6/`:
- [Optimized 76-slide contact sheet](../storage/phase6/optimized-contact-sheet.jpg)
- [Before (180s, teacher blocks A & C, footer present)](../storage/phase6/opt-before-180.png)
- [After (grouped with 240s clear-board representative, channel crop applied)](../storage/phase6/opt-after-rep240.png)

## 7. Distinct question preservation results

All 11 excluded primary frames (`180s`, `480s`, `2460s`, `2640s`, `2820s`, `2880s`, `3000s`, `3480s`, `4980s`, `5040s`, `5100s`) were manually verified against `storage/phase6/contact-sheet.jpg` and `docs/PHASE6_REFERENCES.json` as true repeated observations of the same slide. **Zero** distinct questions, **zero** answer reveals, and **zero** meaningful annotation states were excluded.

## 8. Resource consumption

- Wall duration: **37.76 s** (host run via `benchmark_slides.py`)
- Python CPU time: **24.26 s**; Child FFmpeg CPU time: **20.04 s**
- Peak Python RSS: **707,166,208 bytes**; Peak child RSS: **43,040,768 bytes** (macOS `ru_maxrss` units in bytes)
- Output logical storage: **152,573,530 bytes**

## 9. Actual automated test results

- **Backend pytest**: `245 passed, 1 skipped` (opt-in `PHASE6_REAL_DATA` test skipped when env var unset), including 5 new Phase 6 optimization regression tests.
- **Ruff lint & format**: Passed (`64` Python files).
- **Strict mypy**: Passed (`56` source/test/script files).
- **Frontend Vitest**: `40 passed across 6 files`.
- **Frontend ESLint, Prettier, `tsc -b`, Vite build**: Passed.
- **Local Playwright E2E**: `11 passed in 5.7s`.

## 10. Remaining issues and limitations

- **Single authorized lecture dataset**: Only one authorized WBPSC IDO lecture (`vqYNwaqFPJM`) was available locally; multi-channel generalization across 3+ distinct YouTube channels could not be benchmarked offline without live YouTube acquisition.
- **40–60% screenshot reduction target**: Achieved **12.6% primary reduction** (11/87) on `vqYNwaqFPJM` because the remaining ~76 frames represent distinct questions, answer reveals, or progressive handwritten annotations that must be preserved. Per Section 13, accuracy was prioritized over hitting a numerical reduction quota.
- **Stationary teacher / remaining obstruction**: 58 slides remain `incomplete` (`manual_review=True`) because the teacher remained partially in front of the board across all sampled observations of those segments.
- **Docker Playwright E2E**: Local Playwright (`11 passed`) was re-run after all edits; Docker container rebuild/re-test was not re-executed in this pass.

## 11. Acceptance criteria status

| Criterion | Status |
|---|---|
| Saved channel crop profiles work reliably | **Passed** (SQLite persistence, API CRUD, aspect/edge validation, fallback tested) |
| Adaptive sampling distributed across video | **Passed** (65 samples distributed across all 4 quarters; regression tested) |
| Best-frame selection improves visual quality | **Passed** (18 `clear_original`, e.g. 240s selected over obstructed 180s) |
| Duplicate removal improves over baseline | **Passed** (11× improvement: 11 vs 1 excluded) |
| Zero distinct reference question states lost | **Passed** (0 lost; all annotations & templates preserved) |
| Quality classifications supported by evidence | **Passed** (`quality_category`, `crop_reliability`, `visible_coverage`, `grouping_confidence`) |
| Unnecessary image storage reduced | **Passed** (-56.6%: 351.8 MB → 152.6 MB) |
| Representative visual comparisons available | **Passed** (`storage/phase6/optimized-contact-sheet.jpg`, `opt-before-180.png`, `opt-after-rep240.png`) |
| Existing reliability & quality checks pass | **Passed** (245 backend tests, 40 frontend tests, 11 E2E, Ruff, mypy, ESLint, Prettier, Vite build) |


---

# Phase 6 Final Stabilization & Multi-Channel Verification Addendum (2026-11-27)

## 1. Stabilization Improvements Implemented

1. **Non-inflated foreground masking (`backend/app/services/imaging/obstruction.py`, `backend/app/domain/slides.py`)**:
   - Removed the rectangular bounding-box fill in `large_components` that inflated 10–15% teacher silhouettes into 35–57% bounding boxes, while setting `mask_dilation_pixels=20` so filled contour silhouettes still cover adjacent hair/clothing fringes without swallowing unrelated visible board text.
2. **Resilient observed-pixel fusion (`backend/app/services/imaging/reconstruction.py`)**:
   - Updated `reconstruct()` to filter candidate observations to the compatible subset passing the visible-region residual check (`fusion_max_residual=0.0008`) instead of aborting the entire group when one observation contains a new annotation or minor shift.
3. **Adaptive sampling distribution & anchor selection (`backend/app/services/imaging/pipeline.py`)**:
   - Distributed `sample_timestamps()` across the strict interior `(start, end)` of each segment instead of clustering all samples at `start + 5s..30s`.
   - Prioritized moderately obstructed segments (`<= 0.25`) before heavily obstructed segments (`> 0.25`) within each temporal quarter, and compared adaptive candidates against the least-obstructed primary in the segment.
4. **Two-stage lightweight slide-transition detection (`backend/app/services/imaging/pipeline.py`)**:
   - Implemented `_scan_missed_transitions()` bounded by `transition_scan_enabled` and `transition_scan_max_probes` (default `12`).
   - Probes interval midpoints at low resolution (`320px` via sparse FFmpeg `-ss` seeking, ~0.8s for 12 probes), compares against adjacent primaries using `compare_visible` (`visible_ssim < 0.85` gate), extracts original-resolution PNGs only for promising transitions, and verifies again at full comparison resolution before inserting chronological segments.
5. **Storage reference integrity guard (`backend/app/services/extraction.py`, `backend/app/services/slides.py`, `backend/app/main.py`)**:
   - Added `SlideService.assert_no_published_slides` wired to `ExtractionService.delete_guard`, returning `409 Conflict` if `DELETE /api/v1/videos/{id}/extraction` is attempted while published slides reference those immutable Phase 5 frames.
6. **Channel crop profile UI (`frontend/src/features/channels/channel-board-profile-modal.tsx`, `frontend/src/features/channels/channels-page.tsx`, `frontend/src/services/channels.ts`, `frontend/src/services/api.ts`)**:
   - Added "Board crop" modal on the Channels page supporting viewing, saving/updating (`PUT /api/v1/channels/{id}/board-profile`), and deleting (`DELETE /api/v1/channels/{id}/board-profile`) per-channel normalized crop profiles.

## 2. Multi-Channel Evaluation & Benchmark Results

Evaluated across three distinct authorized WBPSC IDO channels (<=720p video-only, 60s primary sampling):

- **BSSEI Competitive** (`vqYNwaqFPJM`, 5179s / 86.3m, smartboard + persistent footer + moving teacher, crop `(0, 0, 1, 0.865)`).
- **TWS Academy** (`3jqcXCkRUDI`, 1825.3s / 30.4m, screen-capture PPT + top/bottom red banners + progressive handwriting, crop `(0, 0.045, 1, 0.945)`).
- **VSCE Academy** (`3S2vx41zkgY`, 4142.7s / 69.0m, **separate validation dataset** not used for threshold tuning; dark smartboard + animated bottom ticker + stationary/moving teacher, crop `(0, 0, 1, 0.945)`).

| Metric | BSSEI (`vqYNwaqFPJM`) | TWS (`3jqcXCkRUDI`) | VSCE (`3S2vx41zkgY`, val) |
|---|---:|---:|---:|
| Video duration | 5179.0 s | 1825.3 s | 4142.7 s |
| Primary screenshots | 87 | 31 | 70 |
| Additional adaptive samples | 65 | 18 | 52 |
| Transition-discovered slides | 2 (`4170s`, `4590s`) | 0 | 0 |
| Published slides | 79 | 30 | 61 |
| Redundant primaries excluded | 10 | 1 | 9 |
| Distinct question states lost | **0** | **0** | **0** |
| Duplicate precision / recall | 100% (10/10) / 90.9% (10/11) | 100% (1/1) / 33.3% (1/3) | 100% (9/9) / 39.1% (9/23) |
| `clear_original` | **20** | **27** | 0 |
| `reconstructed` | 0 | 0 | 0 |
| `incomplete` / `manual_review` | 59 / 59 | 3 / 4 | 61 / 61 |
| Wall duration | 42.82 s | 8.70 s | 26.16 s |
| Python / Child FFmpeg CPU | 27.23 s / 24.35 s | 6.86 s / 5.09 s | 20.37 s / 12.93 s |
| Peak Python / Child RSS | 852.5 MB / 58.7 MB | 852.5 MB / 58.7 MB | 852.5 MB / 58.7 MB |
| Output logical storage | 163.0 MB | 30.7 MB | 97.7 MB |

*Notes*:
- All excluded primaries across all three channels (`10` on BSSEI, `1` on TWS, `9` on VSCE) were verified against their contact sheets as true repeated observations of the same slide/annotation state (**100% duplicate precision, 0 distinct questions or answer reveals lost**). Lower recall on VSCE reflects conservative preservation when the teacher adds progressive red underlines or moves across dark background regions.
- On VSCE (`3S2vx41zkgY`), 61/61 slides remain `incomplete` (`manual_review=True`) honestly because the teacher remains standing in front of the smartboard across all sampled observations of those segments.
- Peak Python RSS (`852.5 MB`) is cumulative process `ru_maxrss` across all 3 sequential runs in the same Python process.

## 3. Visual Artifacts for Review

Retained locally in ignored `storage/phase6/eval/`:
- BSSEI contact sheet: `storage/phase6/eval/contact-final-vqYNwaqFPJM.jpg` (plus `storage/phase6/opt-before-180.png`, `storage/phase6/opt-after-rep240.png`)
- TWS contact sheets & before/after: `storage/phase6/eval/contact-3jqcXCkRUDI.jpg`, `storage/phase6/eval/contact-final-3jqcXCkRUDI.jpg`, `storage/phase6/eval/tws-before-300.png`, `storage/phase6/eval/tws-after-300.png`
- VSCE contact sheets & before/after: `storage/phase6/eval/contact-3S2vx41zkgY.jpg`, `storage/phase6/eval/contact-final-3S2vx41zkgY.jpg`, `storage/phase6/eval/vsce-before-780.png`, `storage/phase6/eval/vsce-after-rep840.png`

## 4. Automated, Real-Data, and Docker Verification

- **Backend pytest (with `PHASE6_REAL_DATA=/tmp/phase6-data`)**: `248 passed` (0 skipped), including `test_authorized_real_preservation_and_reconstruction`, `test_delete_extracted_frames_blocked_when_slides_exist`, and `test_transition_scan_discovers_inter_primary_slide`.
- **Ruff lint & format**: Passed (`56`+ Python files).
- **Strict mypy**: Passed (`56` source/test/script files).
- **Frontend ESLint, Prettier, `tsc -b`, Vitest (`40 passed`), Vite build**: Passed.
- **Docker Compose**: Rebuilt and started `backend` (healthy) and `frontend` (started); `alembic current` at `c3d8e1f2a4b5 (head)` with `alembic check` reporting no pending operations.
- **Docker Playwright E2E**: `11 passed in 2.1s` against `http://127.0.0.1:8080` (following 1 initial flaky run on `extraction.spec.ts` `6030` input race).
- **Docker API workflow, recovery & persistence**: Verified `409` extraction-delete guard while slides exist, channel crop profile `PUT`/`GET`/`DELETE`, slide `cancel` -> `retry` (`202`) -> `docker compose restart backend` automatic recovery (`processed`, `78` slides, `11` duplicates, `65` extra samples, `58` review), `docker compose up -d --force-recreate` persistence of slide outputs, preview PNGs (`981,914` bytes), and channel crop profiles.

## 5. Remaining Limitations & Unresolved Criteria

- **Stationary teacher obstruction**: `59/79` slides on BSSEI and `61/61` on VSCE remain `incomplete` (`manual_review=True`) because the teacher remains partially in front of the smartboard throughout those segments; permanently occluded regions cannot be recovered without hallucination.
- **Transition scan bound**: `transition_scan_max_probes` defaults to `12` evenly spaced interval midpoints (~0.8s overhead); slides displayed entirely between unprobed 60s intervals can still be missed.
- **Channel crop UI test coverage**: The new `ChannelBoardProfileModal` is verified via ESLint, `tsc -b`, Vite build, and live Docker API CRUD/persistence; dedicated Vitest/Playwright UI specs for the modal can be added if desired.
