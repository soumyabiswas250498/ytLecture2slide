"""Complementary, obstruction-aware, and region-based slide similarity metrics."""

from dataclasses import dataclass

import cv2
import numpy as np
from skimage.metrics import structural_similarity

from app.domain.slides import SlideConfig
from app.services.imaging.board import Image


@dataclass(frozen=True)
class Similarity:
    ssim: float
    changed_fraction: float
    edge_agreement: float
    hash_distance: int
    candidate: bool
    duplicate: bool


@dataclass(frozen=True)
class VisibleComparison:
    visible_fraction: float
    visible_ssim: float
    visible_changed_fraction: float
    edge_agreement: float
    max_cell_changed: float
    changed_cells: int
    has_new_annotation: bool
    same_slide_candidate: bool
    duplicate: bool
    reason: str


def _analysis_size(width: int, height: int, target_width: int) -> tuple[int, int]:
    return (
        min(width, target_width),
        max(8, round(height * min(1, target_width / width))),
    )


def compare(left: Image, right: Image, config: SlideConfig) -> Similarity:
    if left.shape != right.shape:
        return Similarity(0, 1, 0, 64, False, False)
    height, width = left.shape[:2]
    size = _analysis_size(width, height, config.comparison_width)
    a, b = [cv2.resize(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), size) for im in (left, right)]
    score = float(structural_similarity(a, b, data_range=255))  # type: ignore[no-untyped-call]
    # Count differences at original resolution so a small answer/tick is not downsampled away.
    changed = float(np.mean(np.max(cv2.absdiff(left, right), axis=2) > config.pixel_difference))
    ea, eb = [
        cv2.Canny(im, config.edge_low_threshold, config.edge_high_threshold) > 0 for im in (a, b)
    ]
    edge = float(int(np.sum(ea & eb)) / max(1, int(np.sum(ea | eb))))
    hashes = []
    for im in (a, b):
        low = cv2.dct(cv2.resize(im, (32, 32)).astype(np.float32))[:8, :8]
        hashes.append(low > np.median(low[1:]))
    distance = int(np.count_nonzero(hashes[0] != hashes[1]))
    duplicate = score >= config.duplicate_ssim and changed <= config.duplicate_max_changed
    candidate = (
        score >= config.group_ssim
        and edge >= config.group_edge_agreement
        and changed <= config.group_max_changed
    )
    return Similarity(score, changed, edge, distance, candidate or duplicate, duplicate)


def compare_visible(
    left: Image,
    right: Image,
    mask_left: Image | None,
    mask_right: Image | None,
    config: SlideConfig,
) -> VisibleComparison:
    """Compare mutually visible board regions, excluding suspected teacher obstruction."""
    if left.shape != right.shape:
        return VisibleComparison(
            0.0, 0.0, 1.0, 0.0, 1.0, 16, False, False, False, "Frame dimensions differ."
        )
    height, width = left.shape[:2]
    vis = np.ones((height, width), dtype=bool)
    if mask_left is not None:
        vis &= mask_left == 0
    if mask_right is not None:
        vis &= mask_right == 0
    vis = cv2.erode(vis.astype(np.uint8), np.ones((3, 3), dtype=np.uint8)) > 0
    visible_fraction = float(np.mean(vis))
    if visible_fraction < 0.25:
        return VisibleComparison(
            visible_fraction,
            0.0,
            1.0,
            0.0,
            1.0,
            16,
            False,
            False,
            False,
            "Insufficient mutually visible board area to confirm similarity.",
        )

    size = _analysis_size(width, height, config.comparison_width)
    a_gray, b_gray = [
        cv2.resize(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), size) for im in (left, right)
    ]
    vis_small = cv2.resize(vis.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    if not np.any(vis_small):
        vis_small = np.ones_like(a_gray, dtype=bool)

    _, ssim_map = structural_similarity(  # type: ignore[no-untyped-call]
        a_gray, b_gray, data_range=255, full=True
    )
    visible_ssim = float(np.mean(ssim_map[vis_small]))

    ea = cv2.Canny(a_gray, config.edge_low_threshold, config.edge_high_threshold) > 0
    eb = cv2.Canny(b_gray, config.edge_low_threshold, config.edge_high_threshold) > 0
    ea_vis = ea & vis_small
    eb_vis = eb & vis_small
    union_edges = int(np.sum(ea_vis | eb_vis))
    edge_agreement = float(int(np.sum(ea_vis & eb_vis)) / max(1, union_edges))

    # Detect newly added strokes/highlights in the right frame on mutually visible pixels.
    dilated_ea = cv2.dilate(ea.astype(np.uint8), np.ones((3, 3), dtype=np.uint8)) > 0
    new_edges = eb_vis & ~dilated_ea
    new_edge_fraction = float(int(np.sum(new_edges)) / max(1, int(np.sum(vis_small))))

    blur_a = cv2.GaussianBlur(left, (3, 3), 0)
    blur_b = cv2.GaussianBlur(right, (3, 3), 0)
    diff_blur = np.max(cv2.absdiff(blur_a, blur_b), axis=2) > config.pixel_difference
    visible_changed_fraction = float(np.mean(diff_blur[vis]))

    diff_raw = np.max(cv2.absdiff(left, right), axis=2) > max(28, config.pixel_difference)
    bright_added = (np.max(right.astype(np.int16) - left.astype(np.int16), axis=2) > 40) & vis
    bright_added_fraction = float(int(np.sum(bright_added)) / max(1, int(np.sum(vis))))

    # 4x4 grid inspection to catch localized answer ticks or question text swaps.
    cell_changed: list[float] = []
    row_step = max(1, height // 4)
    col_step = max(1, width // 4)
    for r in range(4):
        for c in range(4):
            r0, r1 = r * row_step, height if r == 3 else (r + 1) * row_step
            c0, c1 = c * col_step, width if c == 3 else (c + 1) * col_step
            cell_vis = vis[r0:r1, c0:c1]
            if float(np.mean(cell_vis)) >= 0.40:
                cell_changed.append(float(np.mean(diff_raw[r0:r1, c0:c1][cell_vis])))
    max_cell_changed = max(cell_changed, default=1.0)
    changed_cells = sum(val > 0.015 for val in cell_changed)

    has_new_annotation = (
        new_edge_fraction >= config.dedup_annotation_threshold or bright_added_fraction >= 0.0025
    ) and visible_ssim >= 0.85

    same_slide_candidate = (
        visible_ssim >= config.obstruction_aware_ssim
        and edge_agreement >= config.group_edge_agreement
        and visible_changed_fraction <= 0.04
    )

    is_duplicate = (
        visible_ssim >= config.dedup_visible_ssim
        and visible_changed_fraction <= config.dedup_visible_max_changed
        and max_cell_changed <= config.dedup_max_cell_changed
        and edge_agreement >= 0.88
        and changed_cells == 0
        and not has_new_annotation
    )

    if is_duplicate:
        reason = (
            f"Mutually visible board regions match (SSIM={visible_ssim:.3f}, "
            f"changed={visible_changed_fraction:.4f}, edge={edge_agreement:.2f})."
        )
    elif has_new_annotation:
        reason = (
            f"New annotation or answer marking detected on visible board "
            f"(new_edges={new_edge_fraction:.4f}, bright={bright_added_fraction:.4f})."
        )
    elif same_slide_candidate:
        reason = (
            f"Same-slide candidate with localized differences "
            f"(SSIM={visible_ssim:.3f}, max_cell={max_cell_changed:.3f})."
        )
    else:
        reason = (
            f"Distinct slide or layout change (visible_SSIM={visible_ssim:.3f}, "
            f"changed_cells={changed_cells})."
        )

    return VisibleComparison(
        visible_fraction=visible_fraction,
        visible_ssim=visible_ssim,
        visible_changed_fraction=visible_changed_fraction,
        edge_agreement=edge_agreement,
        max_cell_changed=max_cell_changed,
        changed_cells=changed_cells,
        has_new_annotation=has_new_annotation,
        same_slide_candidate=same_slide_candidate,
        duplicate=is_duplicate,
        reason=reason,
    )
