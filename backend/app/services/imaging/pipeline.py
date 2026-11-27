"""Independent, bounded slide generation from a validated Phase 5 generation."""

import os
import shutil
import struct
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from app.domain.extraction import (
    CancellationSignal,
    ExtractionCancelled,
    FrameExtractor,
    FrameMetadata,
)
from app.domain.slides import (
    FrameDecision,
    GroupingConfidence,
    Slide,
    SlideConfig,
    SlideError,
    SlideManifest,
    SlideQuality,
)
from app.infrastructure.frame_extractor import read_manifest, validate_png
from app.services.imaging.board import Board, Image, isolate_board
from app.services.imaging.obstruction import obstruction_masks
from app.services.imaging.reconstruction import select_best_or_reconstruct
from app.services.imaging.similarity import compare, compare_visible


def sample_timestamps(start: float, end: float, config: SlideConfig, remaining: int) -> list[float]:
    """Distribute samples across the strict interior of a segment."""
    count = min(config.max_samples_per_segment, remaining)
    span = end - start
    if count <= 0 or span <= config.additional_interval:
        return []
    max_slots = int((span - 1e-6) // config.additional_interval)
    if max_slots <= 0:
        return []
    actual_count = min(count, max_slots)
    step = span / (actual_count + 1)
    if step < config.additional_interval:
        return [
            round(start + index * config.additional_interval, 6)
            for index in range(1, actual_count + 1)
            if start + index * config.additional_interval < end
        ]
    return [round(start + index * step, 6) for index in range(1, actual_count + 1)]


def compute_adaptive_budget(duration_seconds: float, config: SlideConfig) -> int:
    """Scale adaptive sampling budget with video duration while respecting configured bounds."""
    if not config.adaptive_enabled:
        return 0
    if config.adaptive_scale_with_duration and duration_seconds > 0:
        scaled = round((duration_seconds / 3600.0) * config.adaptive_samples_per_hour)
        return min(config.max_additional_samples_cap, max(config.max_additional_samples, scaled))
    return config.max_additional_samples


def load_image(path: Path, config: SlideConfig) -> Image:
    if path.is_symlink():
        raise SlideError("Symlink image input rejected.")
    # Header limits apply before OpenCV allocates an untrusted decoded image.
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise SlideError("Expected a PNG image.")
    width, height = struct.unpack(">II", header[16:24])
    if width * height > config.max_image_pixels or min(width, height) < 8:
        raise SlideError("Image dimensions exceed configured limits.")
    validate_png(path, width, height)
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise SlideError("PNG could not be decoded.")
    return image.astype(np.uint8)


def write_image(path: Path, image: Image) -> None:
    if not cv2.imwrite(str(path), image):
        raise SlideError("Could not save processed image.")
    validate_png(path, image.shape[1], image.shape[0])


def resolve_slide_image(directory: Path, extraction_directory: Path, name: str) -> Path:
    """Resolve a slide-referenced image inside the slide generation or extraction root."""
    for root in (directory, extraction_directory):
        target = root / name
        if target.is_symlink():
            raise SlideError("Unsafe slide image path.")
        if target.exists():
            if not target.resolve().is_relative_to(root.resolve()):
                raise SlideError("Unsafe slide image path.")
            return target
    raise SlideError(f"Referenced slide image missing: {name}")


def read_slide_manifest(directory: Path, *, validate_images: bool = True) -> SlideManifest:
    path = directory / "manifest.json"
    if path.is_symlink():
        raise SlideError("Unsafe slide manifest.")
    result = SlideManifest.model_validate_json(path.read_text())
    extraction_dir = Path(result.extraction_directory)
    for slide in result.slides:
        names: list[str] = [
            slide.processed_image_path,
            slide.cropped_image_path,
            slide.original_image_path,
        ]
        if slide.obstruction_mask_path is not None:
            names.append(slide.obstruction_mask_path)
        for name in dict.fromkeys(names):
            target = resolve_slide_image(directory, extraction_dir, name)
            if validate_images:
                load_image(target, result.configuration)
    return result


@dataclass
class _Segment:
    primary_indices: list[int]
    frames: list[FrameMetadata]
    boards: list[Board]
    initial_masks: list[Image]
    duplicate_reasons: list[str] = field(default_factory=list)
    extra_images: list[Image] = field(default_factory=list)
    extra_timestamps: list[float] = field(default_factory=list)
    extra_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    end_timestamp: float = 0.0
    max_initial_obstruction: float = 0.0
    min_initial_obstruction: float = 1.0
    frame_prefix: str = ""


class SlideProcessor:
    def __init__(self, extractor: FrameExtractor | None = None) -> None:
        self.extractor = extractor

    def process(
        self,
        frames: Path,
        output: Path,
        *,
        video_id: int,
        config: SlideConfig,
        source: Path | None = None,
        cancel: CancellationSignal | None = None,
        on_progress: Callable[[int, int, int], None] | None = None,
    ) -> SlideManifest:
        started = time.monotonic()
        inputs = read_manifest(frames)
        if inputs.video_id != str(video_id):
            raise SlideError("Extraction belongs to a different video.")
        if output.resolve().is_relative_to(frames.resolve()):
            raise SlideError("Processed outputs must be separate from original screenshots.")
        source_identity = None
        if config.adaptive_enabled and source is not None and self.extractor is not None:
            stat = source.stat()
            source_identity = (str(source.resolve()), stat.st_size, stat.st_mtime_ns)
            if source_identity != (
                inputs.source_path,
                inputs.source_size_bytes,
                inputs.source_mtime_ns,
            ):
                raise SlideError("Adaptive source identity differs from the extracted video.")
        output.mkdir(parents=True, exist_ok=False)

        def check() -> None:
            if cancel and cancel.is_set():
                raise ExtractionCancelled("Slide processing interrupted.")
            if shutil.disk_usage(output).free < config.min_free_disk_mb * 1024 * 1024:
                raise SlideError("Insufficient free space for slide output.")

        # Pass 1: Load all primaries, isolate boards, and segment chronologically
        # without uncontrolled transitive drift.
        segments: list[_Segment] = []
        total_primaries = len(inputs.frames)

        for index, frame in enumerate(inputs.frames):
            check()
            original = load_image(frames / frame.filename, config)
            board = isolate_board(original, config)
            init_mask = obstruction_masks([board.image], config)[0]
            obs_frac = float(np.mean(init_mask > 0))

            if segments:
                cur = segments[-1]
                quick = compare(cur.boards[0].image, board.image, config)
                if quick.ssim >= 0.72 and board.coordinates == cur.boards[0].coordinates:
                    m_anchor, m_cur = obstruction_masks([cur.boards[0].image, board.image], config)
                    anchor_cmp = compare_visible(
                        cur.boards[0].image, board.image, m_anchor, m_cur, config
                    )
                    if len(cur.boards) > 1:
                        m_prev, m_cur_p = obstruction_masks(
                            [cur.boards[-1].image, board.image], config
                        )
                        prev_cmp = compare_visible(
                            cur.boards[-1].image, board.image, m_prev, m_cur_p, config
                        )
                    else:
                        prev_cmp = anchor_cmp
                    if anchor_cmp.duplicate and prev_cmp.duplicate:
                        cur.primary_indices.append(index)
                        cur.frames.append(frame)
                        cur.boards.append(board)
                        cur.initial_masks.append(m_cur)
                        cur.duplicate_reasons.append(anchor_cmp.reason)
                        cur.min_initial_obstruction = min(
                            cur.min_initial_obstruction, float(np.mean(m_cur > 0))
                        )
                        cur.max_initial_obstruction = max(
                            cur.max_initial_obstruction, float(np.mean(m_cur > 0))
                        )
                        if on_progress:
                            on_progress(index + 1, total_primaries, 0)
                        continue

            seg = _Segment(
                primary_indices=[index],
                frames=[frame],
                boards=[board],
                initial_masks=[init_mask],
                warnings=[board.warning] if board.warning else [],
                min_initial_obstruction=obs_frac,
                max_initial_obstruction=obs_frac,
            )
            segments.append(seg)
            if on_progress:
                on_progress(index + 1, total_primaries, 0)

        for seg_idx, seg in enumerate(segments):
            if seg_idx + 1 < len(segments):
                seg.end_timestamp = segments[seg_idx + 1].frames[0].actual_timestamp
            else:
                seg.end_timestamp = inputs.end_timestamp

        # Pass 1.5: Lightweight low-resolution transition scan between 60s primaries.
        if (
            config.transition_scan_enabled
            and config.transition_scan_max_probes > 0
            and self.extractor is not None
            and source is not None
            and len(segments) >= 2
        ):
            self._scan_missed_transitions(
                segments=segments,
                output=output,
                video_id=video_id,
                source=source,
                config=config,
                check=check,
                cancel=cancel,
            )

        # Pass 2: Whole-video priority-based adaptive sampling across temporal quarters.
        sampled: list[float] = []
        total_budget = compute_adaptive_budget(inputs.video_duration, config)
        if config.adaptive_enabled and self.extractor and source and total_budget > 0:
            self._run_adaptive_sampling(
                segments=segments,
                total_budget=total_budget,
                duration=inputs.video_duration,
                output=output,
                video_id=video_id,
                source=source,
                config=config,
                sampled=sampled,
                check=check,
                cancel=cancel,
            )

        # Pass 3: Best-frame selection, safe reconstruction, quality classification, and output.
        slides: list[Slide] = []
        decisions_by_index: dict[int, FrameDecision] = {}

        for seg_idx, seg in enumerate(segments):
            check()
            group_num = seg_idx + 1
            slide_num = len(slides) + 1
            slide_id = f"slide_{slide_num:05d}"

            all_images = [b.image for b in seg.boards] + seg.extra_images
            is_adaptive_flags = [False] * len(seg.boards) + [True] * len(seg.extra_images)
            masks = obstruction_masks(all_images, config)

            selection = select_best_or_reconstruct(
                all_images, masks, config, is_adaptive=is_adaptive_flags
            )
            chosen_idx = selection.chosen_index
            is_adaptive_chosen = is_adaptive_flags[chosen_idx]

            if not is_adaptive_chosen:
                rep_primary_pos = chosen_idx
            else:
                # Pick the primary with lowest initial obstruction as the primary anchor reference.
                rep_primary_pos = min(
                    range(len(seg.boards)),
                    key=lambda k: float(np.mean(seg.initial_masks[k] > 0)),
                )
            rep_frame = seg.frames[rep_primary_pos]
            rep_board = seg.boards[rep_primary_pos]
            rep_mask = masks[chosen_idx]

            warnings = list(seg.warnings)
            if selection.warning:
                warnings.append(selection.warning)

            # Determine quality indicators and manual review status.
            grouping_confidence: GroupingConfidence = (
                "high"
                if (len(all_images) >= 2 and not rep_board.fallback)
                else ("medium" if not rep_board.fallback else "low")
            )
            manual_review = (
                selection.quality_category in {"reconstructed", "incomplete", "uncertain"}
                or rep_board.fallback
            )
            incomplete = selection.quality_category in {"incomplete", "uncertain"}

            # Storage optimization: reference immutable Phase 5 primary PNG when unmodified.
            if seg.frame_prefix:
                original_path = f"original_{slide_num:05d}.png"
                shutil.copy2(output / seg.frame_prefix / rep_frame.filename, output / original_path)
            else:
                original_path = rep_frame.filename
            if rep_board.modified:
                cropped_path = f"crop_{slide_num:05d}.png"
                write_image(output / cropped_path, rep_board.image)
            else:
                cropped_path = original_path

            if selection.method == "original" and not is_adaptive_chosen:
                processed_path = cropped_path
            else:
                processed_path = f"slide_{slide_num:05d}.png"
                write_image(output / processed_path, selection.image)

            mask_path: str | None = None
            if config.save_diagnostics:
                mask_path = f"mask_{slide_num:05d}.png"
                write_image(output / mask_path, rep_mask)

            source_frame_ids = [
                f"{seg.frame_prefix}/{f.filename}" if seg.frame_prefix else f.filename
                for f in seg.frames
            ]
            source_timestamps = [f.actual_timestamp for f in seg.frames]
            if selection.method != "original" or is_adaptive_chosen:
                source_frame_ids = source_frame_ids + seg.extra_ids
                source_timestamps = source_timestamps + seg.extra_timestamps

            slide = Slide(
                slide_id=slide_id,
                source_frame_ids=source_frame_ids,
                source_timestamps=source_timestamps,
                additional_sampled_timestamps=seg.extra_timestamps,
                processed_image_path=processed_path,
                cropped_image_path=cropped_path,
                obstruction_mask_path=mask_path,
                original_image_path=original_path,
                board_coordinates=rep_board.coordinates,
                reconstruction_method=selection.method,
                quality=SlideQuality(
                    obstruction_fraction=selection.obstruction_fraction,
                    unresolved_fraction=selection.unresolved_fraction,
                    sharpness=selection.sharpness,
                    visible_coverage=1.0 - selection.obstruction_fraction,
                    clarity_score=selection.sharpness,
                    crop_reliability=rep_board.reliability,
                    grouping_confidence=grouping_confidence,
                ),
                quality_category=selection.quality_category,
                selection_reason=selection.selection_reason,
                duplicate_group=f"candidate_{group_num:05d}",
                warnings=list(dict.fromkeys(warnings)),
                fallback=rep_board.fallback,
                incomplete=incomplete,
                manual_review=manual_review,
            )
            slides.append(slide)

            # Record chronological decisions for every primary frame in this segment.
            dup_cursor = 0
            if seg.primary_indices:
                for local_pos, (p_idx, p_frame) in enumerate(
                    zip(seg.primary_indices, seg.frames, strict=True)
                ):
                    if local_pos == rep_primary_pos:
                        decisions_by_index[p_idx] = FrameDecision(
                            frame_id=p_frame.filename,
                            timestamp=p_frame.actual_timestamp,
                            action="retained",
                            slide_id=slide_id,
                            reason=selection.selection_reason,
                        )
                    else:
                        cmp_reason = (
                            seg.duplicate_reasons[dup_cursor]
                            if dup_cursor < len(seg.duplicate_reasons)
                            else "Same slide observation."
                        )
                        dup_cursor += 1
                        decisions_by_index[p_idx] = FrameDecision(
                            frame_id=p_frame.filename,
                            timestamp=p_frame.actual_timestamp,
                            action="excluded",
                            slide_id=slide_id,
                            reason=(
                                f"Grouped with {slide_id} "
                                f"(rep at {rep_frame.actual_timestamp:g}s); {cmp_reason}"
                            ),
                        )

            if on_progress:
                on_progress(total_primaries, total_primaries, len(sampled))

        decisions = [decisions_by_index[i] for i in range(total_primaries)]
        check()
        if source_identity is not None and source is not None:
            stat = source.stat()
            if source_identity != (str(source.resolve()), stat.st_size, stat.st_mtime_ns):
                raise SlideError("Source video changed during slide processing.")

        manifest = SlideManifest(
            video_id=video_id,
            extraction_directory=str(frames),
            configuration=config,
            slides=slides,
            decisions=decisions,
            input_count=total_primaries,
            additional_sampled_timestamps=sampled,
            duplicate_count=sum(d.action == "excluded" for d in decisions),
            processing_duration=time.monotonic() - started,
            warnings=[
                "Slides displayed entirely between primary samples may be missing.",
                "Reconstruction and obstruction scores are heuristics, not verified accuracy.",
            ],
        )
        if config.adaptive_enabled and (self.extractor is None or source is None):
            manifest.warnings.append(
                "Adaptive sampling unavailable: provide a source video and extractor."
            )
        temporary = output / "manifest.json.tmp"
        with temporary.open("x") as stream:
            stream.write(manifest.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        SlideManifest.model_validate_json(temporary.read_text())
        check()
        temporary.replace(output / "manifest.json")
        read_slide_manifest(output)
        return manifest

    def _run_adaptive_sampling(
        self,
        *,
        segments: list[_Segment],
        total_budget: int,
        duration: float,
        output: Path,
        video_id: int,
        source: Path,
        config: SlideConfig,
        sampled: list[float],
        check: Callable[[], None],
        cancel: CancellationSignal | None,
    ) -> None:
        """Distribute adaptive samples across temporal quarters, prioritizing obstructed runs."""
        assert self.extractor is not None
        num_buckets = min(4, max(1, len(segments)))
        bucket_span = max(1.0, duration) / num_buckets
        buckets: list[list[int]] = [[] for _ in range(num_buckets)]
        for idx, seg in enumerate(segments):
            if seg.min_initial_obstruction <= config.clear_obstruction_threshold:
                continue
            b_idx = min(num_buckets - 1, int(seg.frames[0].actual_timestamp / bucket_span))
            buckets[b_idx].append(idx)

        for bucket in buckets:
            # Prioritize moderately obstructed slides (likely clearable in 1-2 samples)
            # before heavily obstructed segments so stationary obstructions do not starve them.
            bucket.sort(
                key=lambda i: (
                    segments[i].min_initial_obstruction > 0.25,
                    segments[i].min_initial_obstruction,
                )
            )

        # Round-robin across temporal buckets so early segments never starve later ones.
        ordered_indices: list[int] = []
        while any(buckets):
            for bucket in buckets:
                if bucket:
                    ordered_indices.append(bucket.pop(0))

        for seg_idx in ordered_indices:
            if len(sampled) >= total_budget:
                break
            check()
            seg = segments[seg_idx]
            anchor_pos = min(
                range(len(seg.boards)),
                key=lambda k: float(np.mean(seg.initial_masks[k] > 0)),
            )
            anchor_frame = seg.frames[anchor_pos]
            anchor_board = seg.boards[anchor_pos]
            times = sample_timestamps(
                seg.frames[-1].actual_timestamp,
                seg.end_timestamp,
                config,
                total_budget - len(sampled),
            )
            if not times:
                continue
            extra_dir = output / f"samples_{seg_idx:05d}"
            extra = self.extractor.extract(
                source, extra_dir, video_id=str(video_id), timestamps=times, cancel=cancel
            )
            for item in extra.frames:
                sampled.append(item.actual_timestamp)
                if not anchor_frame.actual_timestamp < item.actual_timestamp < seg.end_timestamp:
                    seg.warnings.append(
                        "Additional source PTS crossed candidate boundary; rejected."
                    )
                    continue
                check()
                candidate = isolate_board(load_image(extra_dir / item.filename, config), config)
                m_anc, cand_mask = obstruction_masks([anchor_board.image, candidate.image], config)
                cmp = compare_visible(anchor_board.image, candidate.image, m_anc, cand_mask, config)
                if (
                    cmp.same_slide_candidate
                    and not cmp.has_new_annotation
                    and candidate.coordinates == anchor_board.coordinates
                ):
                    seg.extra_images.append(candidate.image)
                    seg.extra_timestamps.append(item.actual_timestamp)
                    seg.extra_ids.append(f"{extra_dir.name}/{item.filename}")
                    cand_obs = float(np.mean(cand_mask > 0))
                    # Stop sampling this segment early if a clear observation is found.
                    if cand_obs <= config.clear_obstruction_threshold:
                        break
                    if len(seg.extra_images) + len(seg.boards) >= config.max_fusion_frames:
                        break
                else:
                    seg.warnings.append(
                        f"Extra frame at {item.actual_timestamp:g}s retained; "
                        "compatibility uncertain."
                    )

    def _scan_missed_transitions(
        self,
        *,
        segments: list[_Segment],
        output: Path,
        video_id: int,
        source: Path,
        config: SlideConfig,
        check: Callable[[], None],
        cancel: CancellationSignal | None,
    ) -> None:
        """Probe interval midpoints at low resolution and extract full frames for new slides."""
        assert self.extractor is not None
        candidates: list[tuple[int, float]] = []
        for idx in range(len(segments) - 1):
            t_start = segments[idx].frames[-1].actual_timestamp
            t_end = segments[idx + 1].frames[0].actual_timestamp
            if t_end - t_start >= 40.0:
                candidates.append((idx, round((t_start + t_end) / 2.0, 3)))
        if not candidates:
            return
        max_probes = config.transition_scan_max_probes
        if len(candidates) > max_probes:
            step = len(candidates) / max_probes
            candidates = [candidates[int(i * step)] for i in range(max_probes)]

        promising: list[tuple[int, float]] = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for probe_i, (seg_idx, ts) in enumerate(candidates):
                check()
                if cancel and cancel.is_set():
                    raise ExtractionCancelled("Transition scan interrupted.")
                probe_path = tmp_dir / f"probe_{probe_i:04d}.jpg"
                proc = subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-ss",
                        f"{ts:.3f}",
                        "-i",
                        str(source),
                        "-vf",
                        "scale=320:-1",
                        "-frames:v",
                        "1",
                        str(probe_path),
                    ],
                    capture_output=True,
                    timeout=15,
                    check=False,
                )
                if proc.returncode != 0 or not probe_path.is_file():
                    continue
                probe_raw = cv2.imread(str(probe_path), cv2.IMREAD_COLOR)
                if probe_raw is None:
                    continue
                probe_board = isolate_board(probe_raw.astype(np.uint8), config)
                h, w = probe_board.image.shape[:2]
                prev_img = cv2.resize(segments[seg_idx].boards[-1].image, (w, h)).astype(np.uint8)
                next_img = cv2.resize(
                    segments[seg_idx + 1].boards[0].image, (w, h)
                ).astype(np.uint8)
                m_prev, m_probe_p = obstruction_masks([prev_img, probe_board.image], config)
                m_next, m_probe_n = obstruction_masks([next_img, probe_board.image], config)
                cmp_prev = compare_visible(prev_img, probe_board.image, m_prev, m_probe_p, config)
                cmp_next = compare_visible(next_img, probe_board.image, m_next, m_probe_n, config)
                # 320px probes have slight downscale blur; use 0.85 SSIM gate before full-res check.
                if (
                    cmp_prev.visible_ssim < 0.85
                    and cmp_next.visible_ssim < 0.85
                    and cmp_prev.visible_fraction >= 0.25
                    and cmp_next.visible_fraction >= 0.25
                ):
                    promising.append((seg_idx, ts))

        if not promising:
            return
        trans_dir = output / "transitions"
        extracted = self.extractor.extract(
            source,
            trans_dir,
            video_id=str(video_id),
            timestamps=[ts for _, ts in promising],
            cancel=cancel,
        )
        # Verify at original resolution before inserting as a distinct slide segment.
        inserted: list[tuple[int, _Segment]] = []
        for (seg_idx, _), item in zip(promising, extracted.frames, strict=False):
            check()
            t_start = segments[seg_idx].frames[-1].actual_timestamp
            t_end = segments[seg_idx + 1].frames[0].actual_timestamp
            if not t_start < item.actual_timestamp < t_end:
                continue
            original = load_image(trans_dir / item.filename, config)
            board = isolate_board(original, config)
            prev_b = segments[seg_idx].boards[-1].image
            next_b = segments[seg_idx + 1].boards[0].image
            m_p, m_bp = obstruction_masks([prev_b, board.image], config)
            m_n, m_bn = obstruction_masks([next_b, board.image], config)
            full_prev = compare_visible(prev_b, board.image, m_p, m_bp, config)
            full_next = compare_visible(next_b, board.image, m_n, m_bn, config)
            if full_prev.same_slide_candidate or full_next.same_slide_candidate:
                continue
            init_mask = obstruction_masks([board.image], config)[0]
            obs_frac = float(np.mean(init_mask > 0))
            seg = _Segment(
                primary_indices=[],
                frames=[item],
                boards=[board],
                initial_masks=[init_mask],
                warnings=(
                    ([board.warning] if board.warning else [])
                    + ["Discovered via inter-primary transition scan."]
                ),
                end_timestamp=t_end,
                min_initial_obstruction=obs_frac,
                max_initial_obstruction=obs_frac,
                frame_prefix=trans_dir.name,
            )
            inserted.append((seg_idx, seg))
        for seg_idx, seg in reversed(inserted):
            segments[seg_idx].end_timestamp = seg.frames[0].actual_timestamp
            segments.insert(seg_idx + 1, seg)
