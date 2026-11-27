"""Independent, bounded slide generation from a validated Phase 5 generation."""

import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from app.domain.extraction import CancellationSignal, ExtractionCancelled, FrameExtractor
from app.domain.slides import (
    FrameDecision,
    Slide,
    SlideConfig,
    SlideError,
    SlideManifest,
    SlideQuality,
)
from app.infrastructure.frame_extractor import read_manifest, validate_png
from app.services.imaging.board import Image, isolate_board
from app.services.imaging.obstruction import obstruction_masks
from app.services.imaging.reconstruction import reconstruct
from app.services.imaging.similarity import compare


def sample_timestamps(start: float, end: float, config: SlideConfig, remaining: int) -> list[float]:
    """Strict interior only; no sample at either primary boundary."""
    count = min(config.max_samples_per_segment, remaining)
    return [
        round(start + index * config.additional_interval, 6)
        for index in range(1, count + 1)
        if start + index * config.additional_interval < end
    ]


def load_image(path: Path, config: SlideConfig) -> Image:
    if path.is_symlink():
        raise SlideError("Symlink image input rejected.")
    # Header limits apply before OpenCV allocates an untrusted decoded image.
    import struct

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


def read_slide_manifest(directory: Path, *, validate_images: bool = True) -> SlideManifest:
    path = directory / "manifest.json"
    if path.is_symlink():
        raise SlideError("Unsafe slide manifest.")
    result = SlideManifest.model_validate_json(path.read_text())
    for slide in result.slides:
        for name in (
            slide.processed_image_path,
            slide.cropped_image_path,
            slide.obstruction_mask_path,
            slide.original_image_path,
        ):
            target = directory / name
            if target.is_symlink() or not target.resolve().is_relative_to(directory.resolve()):
                raise SlideError("Unsafe slide image path.")
            if validate_images:
                load_image(target, result.configuration)
    return result


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
        slides: list[Slide] = []
        decisions: list[FrameDecision] = []
        sampled: list[float] = []
        previous: Image | None = None
        previous_processed: Image | None = None
        group = 0

        def check() -> None:
            if cancel and cancel.is_set():
                raise ExtractionCancelled("Slide processing interrupted.")
            if shutil.disk_usage(output).free < config.min_free_disk_mb * 1024 * 1024:
                raise SlideError("Insufficient free space for slide output.")

        for index, frame in enumerate(inputs.frames):
            check()
            original = load_image(frames / frame.filename, config)
            board = isolate_board(original, config)
            similarity = compare(previous, board.image, config) if previous is not None else None
            redundant_processed = (
                previous_processed is not None
                and compare(previous_processed, board.image, config).duplicate
            )
            if similarity and similarity.duplicate and redundant_processed:
                slide = slides[-1]
                slide.source_frame_ids.append(frame.filename)
                slide.source_timestamps.append(frame.actual_timestamp)
                decisions.append(
                    FrameDecision(
                        frame_id=frame.filename,
                        timestamp=frame.actual_timestamp,
                        action="excluded",
                        slide_id=slide.slide_id,
                        reason="Near-identical full-resolution pixels and SSIM; source preserved.",
                    )
                )
                if on_progress:
                    on_progress(index + 1, len(inputs.frames), len(sampled))
                continue
            # Shared templates only nominate adaptive candidates. A distinct primary
            # remains its own group unless both original and processed pixels are redundant.
            group += 1
            images = [board.image]
            extra_times: list[float] = []
            extra_ids: list[str] = []
            warnings = [board.warning] if board.warning else []
            mask = obstruction_masks(images, config)[0]
            end = (
                inputs.frames[index + 1].actual_timestamp
                if index + 1 < len(inputs.frames)
                else inputs.end_timestamp
            )
            # Sparse sampling cannot establish a known slide interval. Every extra observation
            # must therefore pass its own content/annotation compatibility gate before fusion.
            if (
                config.adaptive_enabled
                and self.extractor
                and source
                and (np.any(mask) or similarity is None or not similarity.duplicate)
            ):
                times = sample_timestamps(
                    frame.actual_timestamp,
                    end,
                    config,
                    config.max_additional_samples - len(sampled),
                )
                if times:
                    extra_dir = output / f"samples_{index:05d}"
                    extra = self.extractor.extract(
                        source, extra_dir, video_id=str(video_id), timestamps=times, cancel=cancel
                    )
                    for item in extra.frames:
                        sampled.append(item.actual_timestamp)
                        if not frame.actual_timestamp < item.actual_timestamp < end:
                            warnings.append(
                                "Additional source PTS crossed candidate boundary; rejected."
                            )
                            continue
                        check()
                        candidate = isolate_board(
                            load_image(extra_dir / item.filename, config), config
                        )
                        metric = compare(board.image, candidate.image, config)
                        if (
                            metric.candidate
                            and candidate.coordinates == board.coordinates
                            and len(images) < config.max_fusion_frames
                        ):
                            images.append(candidate.image)
                            extra_times.append(item.actual_timestamp)
                            extra_ids.append(f"{extra_dir.name}/{item.filename}")
                        else:
                            warnings.append(
                                f"Extra frame at {item.actual_timestamp:g}s retained; "
                                "compatibility uncertain."
                            )
            masks = obstruction_masks(images, config)
            rebuilt = reconstruct(images, masks, config)
            number = len(slides) + 1
            slide_id = f"slide_{number:05d}"
            names = {
                kind: f"{kind}_{number:05d}.png" for kind in ("slide", "crop", "mask", "original")
            }
            write_image(output / names["original"], original)
            write_image(output / names["crop"], board.image)
            write_image(output / names["mask"], masks[0])
            write_image(output / names["slide"], rebuilt.image)
            if rebuilt.warning:
                warnings.append(rebuilt.warning)
            # Heuristics cannot certify permanently hidden content, including a stationary person.
            warnings.append(
                "Visibility is heuristic; stationary or hidden content cannot be certified."
            )
            slide = Slide(
                slide_id=slide_id,
                source_frame_ids=(
                    [frame.filename] + extra_ids
                    if rebuilt.method != "original"
                    else [frame.filename]
                ),
                source_timestamps=(
                    [frame.actual_timestamp] + extra_times
                    if rebuilt.method != "original"
                    else [frame.actual_timestamp]
                ),
                additional_sampled_timestamps=extra_times,
                processed_image_path=names["slide"],
                cropped_image_path=names["crop"],
                obstruction_mask_path=names["mask"],
                original_image_path=names["original"],
                board_coordinates=board.coordinates,
                reconstruction_method=rebuilt.method,
                quality=SlideQuality(
                    obstruction_fraction=float(np.mean(masks[0] > 0)),
                    unresolved_fraction=rebuilt.unresolved_fraction,
                    sharpness=float(
                        cv2.Laplacian(
                            cv2.cvtColor(rebuilt.image, cv2.COLOR_BGR2GRAY), cv2.CV_64F
                        ).var()
                    ),
                ),
                duplicate_group=f"candidate_{group:05d}",
                warnings=list(dict.fromkeys(warnings)),
                fallback=rebuilt.method == "original" or board.fallback,
                incomplete=True,
                manual_review=True,
            )
            slides.append(slide)
            decisions.append(
                FrameDecision(
                    frame_id=frame.filename,
                    timestamp=frame.actual_timestamp,
                    action="retained",
                    slide_id=slide_id,
                    reason="Distinct or uncertain content/annotations; primary preserved.",
                )
            )
            previous = board.image
            previous_processed = rebuilt.image
            if on_progress:
                on_progress(index + 1, len(inputs.frames), len(sampled))
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
            input_count=len(inputs.frames),
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
        # Validate all published metadata and image content before the atomic commit marker.
        SlideManifest.model_validate_json(temporary.read_text())
        check()
        temporary.replace(output / "manifest.json")
        read_slide_manifest(output)
        return manifest
