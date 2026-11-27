"""Complementary metrics; only near-identical full images are redundant."""

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


def compare(left: Image, right: Image, config: SlideConfig) -> Similarity:
    if left.shape != right.shape:
        return Similarity(0, 1, 0, 64, False, False)
    height, width = left.shape[:2]
    size = (
        min(width, config.comparison_width),
        max(8, round(height * min(1, config.comparison_width / width))),
    )
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
