"""Observed-pixel reconstruction with strict annotation-state checks."""

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

from app.domain.slides import SlideConfig, SlideError
from app.services.imaging.board import Image


@dataclass
class Reconstruction:
    image: Image
    method: Literal["original", "masked_pixel_fusion", "temporal_median"]
    unresolved_fraction: float
    warning: str | None


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
    # Differences outside foreground hypotheses can be a new answer, annotation or slide.
    for index, image in enumerate(images[1:], 1):
        common = visible[0] & visible[index]
        size = config.fusion_comparison_blur
        if size > 1:
            common = cv2.erode(common.astype(np.uint8), np.ones((size, size), dtype=np.uint8)) > 0
        left = cv2.GaussianBlur(reference, (size, size), 0) if size > 1 else reference
        right = cv2.GaussianBlur(image, (size, size), 0) if size > 1 else image
        changed = np.max(cv2.absdiff(left, right), axis=2) > config.pixel_difference
        if np.sum(changed & common) / max(1, np.sum(common)) > config.fusion_max_residual:
            return Reconstruction(
                reference.copy(),
                "original",
                unresolved,
                "Content or annotation state differs; original retained.",
            )
    stack = np.stack(images)
    median = np.median(stack, axis=0).astype(np.uint8)
    # A median is only admissible where it is supported by two visible actual pixels.
    agreement = np.stack(
        [
            v & (np.max(cv2.absdiff(im, median), axis=2) <= config.pixel_difference)
            for im, v in zip(images, visible, strict=True)
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
        for index, image in enumerate(images[1:], 1):
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
