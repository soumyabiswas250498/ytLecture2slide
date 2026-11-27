"""Best-frame selection and observed-pixel reconstruction with strict annotation-state checks."""

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

from app.domain.slides import QualityCategory, SlideConfig, SlideError
from app.services.imaging.board import Image


@dataclass
class Reconstruction:
    image: Image
    method: Literal["original", "masked_pixel_fusion", "temporal_median"]
    unresolved_fraction: float
    warning: str | None


@dataclass(frozen=True)
class CandidateScore:
    index: int
    obstruction_fraction: float
    visible_coverage: float
    sharpness: float
    contrast: float
    agreement: float
    total_score: float


@dataclass
class SelectionResult:
    image: Image
    chosen_index: int
    method: Literal["original", "masked_pixel_fusion", "temporal_median"]
    quality_category: QualityCategory
    obstruction_fraction: float
    unresolved_fraction: float
    sharpness: float
    contrast: float
    selection_reason: str
    warning: str | None


def score_candidate(
    image: Image,
    mask: Image,
    index: int,
    config: SlideConfig,
    *,
    agreement: float = 1.0,
) -> CandidateScore:
    """Rank candidate screenshots prioritizing low obstruction and visible text clarity."""
    obstruction_fraction = float(np.mean(mask > 0))
    visible_coverage = 1.0 - obstruction_fraction
    visible = mask == 0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if np.any(visible):
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        sharpness = float(np.var(lap[visible]))
        contrast = float(np.std(gray[visible]))
    else:
        sharpness = 0.0
        contrast = 0.0
    # Visible board coverage dominates; sharpness on obstructed teacher regions is excluded.
    total_score = (
        visible_coverage * 1000.0
        - obstruction_fraction * 500.0
        + min(sharpness, 1000.0) * 0.15
        + min(contrast, 80.0) * 0.5
        + agreement * 50.0
    )
    return CandidateScore(
        index=index,
        obstruction_fraction=obstruction_fraction,
        visible_coverage=visible_coverage,
        sharpness=sharpness,
        contrast=contrast,
        agreement=agreement,
        total_score=total_score,
    )


def align(reference: Image, candidate: Image, config: SlideConfig) -> Image | None:
    if reference.shape != candidate.shape:
        return None
    a, b = [
        cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32) for im in (reference, candidate)
    ]
    shift, response = cv2.phaseCorrelate(a, b)
    if response < config.alignment_min_response:
        # Foreground can dominate phase correlation. Verify stationary local text/edges
        # through mutually matched ORB features rather than relaxing translation limits.
        detector = cv2.ORB_create(nfeatures=1000)  # type: ignore[attr-defined]
        ka, da = detector.detectAndCompute(a.astype(np.uint8), None)
        kb, db = detector.detectAndCompute(b.astype(np.uint8), None)
        if da is None or db is None:
            return None
        matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
        matches = [m for m in matches if m.distance <= config.feature_max_distance]
        if len(matches) < config.feature_min_matches:
            return None
        shifts = np.array(
            [np.array(kb[m.trainIdx].pt) - np.array(ka[m.queryIdx].pt) for m in matches]
        )
        median = np.median(shifts, axis=0)
        inliers = np.max(np.abs(shifts - median), axis=1) <= config.feature_max_inlier_shift
        if np.mean(inliers) < config.feature_min_inlier_fraction:
            return None
        shift = (float(median[0]), float(median[1]))
    if max(abs(shift[0]), abs(shift[1])) > config.alignment_max_shift:
        return None
    # Integer translation avoids resampling text; nontrivial borders are not fabricated.
    dx, dy = round(shift[0]), round(shift[1])
    if dx or dy:
        return None
    return candidate


def reconstruct(
    images: list[Image],
    masks: list[Image],
    config: SlideConfig,
    *,
    method: Literal["masked_pixel_fusion", "temporal_median"] = "masked_pixel_fusion",
) -> Reconstruction:
    if not images or len(images) != len(masks) or len(images) > config.max_fusion_frames:
        raise SlideError("Provide one bounded image/mask pair per observation.")
    reference = images[0]
    if any(
        im.shape != reference.shape or mask.shape != reference.shape[:2]
        for im, mask in zip(images, masks, strict=True)
    ):
        raise SlideError("Reconstruction observations have incompatible dimensions.")
    unresolved = float(np.mean(masks[0] > 0))
    if len(images) < 3 or len(images) != len(masks):
        return Reconstruction(
            reference.copy(),
            "original",
            unresolved,
            "Insufficient independently agreeing observations; original retained.",
        )
    aligned = [align(reference, im, config) for im in images]
    if any(im is None for im in aligned):
        return Reconstruction(
            reference.copy(), "original", unresolved, "Alignment uncertain; original retained."
        )
    visible = [mask == 0 for mask in masks]
    # Filter to observations whose mutually visible regions agree with reference,
    # so one annotated or shifted frame does not block fusion of compatible frames.
    size = config.fusion_comparison_blur
    left = cv2.GaussianBlur(reference, (size, size), 0) if size > 1 else reference
    compatible_indices = [0]
    for index, image in enumerate(images[1:], 1):
        common = visible[0] & visible[index]
        if size > 1:
            common = cv2.erode(common.astype(np.uint8), np.ones((size, size), dtype=np.uint8)) > 0
        if not np.any(common):
            continue
        right = cv2.GaussianBlur(image, (size, size), 0) if size > 1 else image
        changed = np.max(cv2.absdiff(left, right), axis=2) > config.pixel_difference
        if np.sum(changed & common) / max(1, np.sum(common)) <= config.fusion_max_residual:
            compatible_indices.append(index)
    if len(compatible_indices) < 3:
        return Reconstruction(
            reference.copy(),
            "original",
            unresolved,
            "Content or annotation state differs; original retained.",
        )
    compat_images = [images[i] for i in compatible_indices]
    compat_visible = [visible[i] for i in compatible_indices]
    stack = np.stack(compat_images)
    median = np.median(stack, axis=0).astype(np.uint8)
    # A median is only admissible where it is supported by two visible actual pixels.
    agreement = np.stack(
        [
            v & (np.max(cv2.absdiff(im, median), axis=2) <= config.pixel_difference)
            for im, v in zip(compat_images, compat_visible, strict=True)
        ]
    )
    support = np.sum(agreement, axis=0)
    fill = (masks[0] > 0) & (support >= 2)
    if not np.any(fill):
        return Reconstruction(
            reference.copy(),
            "original",
            unresolved,
            "No multiply observed unobstructed replacement pixels.",
        )
    output = reference.copy()
    if method == "temporal_median":
        output[fill] = median[fill]
    else:
        # Copy actual pixels; no synthesis/inpainting of hidden educational content.
        for index, image in enumerate(compat_images[1:], 1):
            chosen = fill & agreement[index]
            output[chosen] = image[chosen]
            fill[chosen] = False
    remaining = (masks[0] > 0) & (support < 2)
    return Reconstruction(
        output,
        method,
        float(np.mean(remaining)),
        "Unobserved regions remain; inspect source screenshots." if np.any(remaining) else None,
    )


def select_best_or_reconstruct(
    images: list[Image],
    masks: list[Image],
    config: SlideConfig,
    *,
    is_adaptive: list[bool] | None = None,
) -> SelectionResult:
    """Prefer the clearest original/adaptive frame; fuse pixels only when obstruction remains."""
    if not images or len(images) != len(masks):
        raise SlideError("Provide matching images and masks for selection.")
    adaptive_flags = is_adaptive if is_adaptive is not None else [False] * len(images)
    scores = [
        score_candidate(im, mask, idx, config)
        for idx, (im, mask) in enumerate(zip(images, masks, strict=True))
    ]
    best = max(scores, key=lambda s: s.total_score)
    best_img = images[best.index]

    if best.obstruction_fraction <= config.clear_obstruction_threshold:
        category: QualityCategory = (
            "improved_original" if adaptive_flags[best.index] else "clear_original"
        )
        reason = (
            f"Selected {'adaptive' if adaptive_flags[best.index] else 'primary'} observation "
            f"(index {best.index}) with low obstruction ({best.obstruction_fraction:.1%}) "
            f"and visible sharpness {best.sharpness:.1f}; fusion unnecessary."
        )
        return SelectionResult(
            image=best_img.copy(),
            chosen_index=best.index,
            method="original",
            quality_category=category,
            obstruction_fraction=best.obstruction_fraction,
            unresolved_fraction=best.obstruction_fraction,
            sharpness=best.sharpness,
            contrast=best.contrast,
            selection_reason=reason,
            warning=None,
        )

    # Attempt safe pixel fusion only when no sufficiently clear single frame exists.
    if len(images) >= 3:
        ordered_indices = [best.index] + [i for i in range(len(images)) if i != best.index]
        bounded_indices = ordered_indices[: config.max_fusion_frames]
        rebuilt = reconstruct(
            [images[i] for i in bounded_indices],
            [masks[i] for i in bounded_indices],
            config,
        )
        if rebuilt.method != "original" and rebuilt.unresolved_fraction < best.obstruction_fraction:
            gray_rebuilt = cv2.cvtColor(rebuilt.image, cv2.COLOR_BGR2GRAY)
            rebuilt_sharpness = float(cv2.Laplacian(gray_rebuilt, cv2.CV_64F).var())
            cat: QualityCategory = (
                "reconstructed"
                if rebuilt.unresolved_fraction <= config.clear_obstruction_threshold
                else "incomplete"
            )
            reason = (
                f"Observed-pixel fusion reduced unresolved obstruction from "
                f"{best.obstruction_fraction:.1%} to {rebuilt.unresolved_fraction:.1%} "
                f"using {len(bounded_indices)} compatible frames."
            )
            return SelectionResult(
                image=rebuilt.image,
                chosen_index=best.index,
                method=rebuilt.method,
                quality_category=cat,
                obstruction_fraction=best.obstruction_fraction,
                unresolved_fraction=rebuilt.unresolved_fraction,
                sharpness=rebuilt_sharpness,
                contrast=best.contrast,
                selection_reason=reason,
                warning=rebuilt.warning,
            )

    cat_fallback: QualityCategory = (
        "incomplete"
        if best.obstruction_fraction > config.clear_obstruction_threshold
        else "uncertain"
    )
    reason_fallback = (
        f"Retained best single observation (index {best.index}, obstruction "
        f"{best.obstruction_fraction:.1%}); reliable fusion unavailable."
    )
    return SelectionResult(
        image=best_img.copy(),
        chosen_index=best.index,
        method="original",
        quality_category=cat_fallback,
        obstruction_fraction=best.obstruction_fraction,
        unresolved_fraction=best.obstruction_fraction,
        sharpness=best.sharpness,
        contrast=best.contrast,
        selection_reason=reason_fallback,
        warning="Potentially obstructed regions remain; inspect source screenshots.",
    )
