"""Conservative board geometry, channel profile validation, and perspective correction."""

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from app.domain.slides import Crop, CropReliability, SlideConfig, SlideError

Image = NDArray[np.uint8]


@dataclass
class Board:
    image: Image
    coordinates: list[tuple[float, float]]
    fallback: bool
    warning: str | None = None
    reliability: CropReliability = "full_frame_fallback"
    modified: bool = False


def full_frame_board(image: Image) -> Board:
    """Return the complete original video frame without cropping or perspective warp."""
    return Board(
        image=image.copy(),
        coordinates=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        fallback=False,
        warning=None,
        reliability="full_frame",
        modified=False,
    )


def order_corners(points: NDArray[Any]) -> NDArray[np.float32]:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    ordered = np.empty((4, 2), dtype=np.float32)
    total, difference = points.sum(axis=1), np.diff(points, axis=1).ravel()
    ordered[0], ordered[2] = points[np.argmin(total)], points[np.argmax(total)]
    ordered[1], ordered[3] = points[np.argmin(difference)], points[np.argmax(difference)]
    if len(np.unique(ordered, axis=0)) != 4:
        raise SlideError("Ambiguous board corners.")
    return ordered


def perspective(image: Image, corners: NDArray[Any]) -> Image:
    points = order_corners(corners)
    a, b, c, d = points
    width = round(max(np.linalg.norm(b - a), np.linalg.norm(c - d)))
    height = round(max(np.linalg.norm(d - a), np.linalg.norm(c - b)))
    if min(width, height) < 2:
        raise SlideError("Board geometry is too small.")
    target = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
    )
    transform = cv2.getPerspectiveTransform(points, target)
    return cv2.warpPerspective(image, transform, (width, height)).astype(np.uint8)


def _apply_crop(
    image: Image,
    crop: Crop,
    reliability: CropReliability,
) -> Board:
    height, width = image.shape[:2]
    x1, y1 = int(crop.left * width), int(crop.top * height)
    x2, y2 = round(crop.right * width), round(crop.bottom * height)
    if x2 - x1 < 2 or y2 - y1 < 2:
        raise SlideError("Crop is too small for this image.")
    is_full = x1 == 0 and y1 == 0 and x2 == width and y2 == height
    return Board(
        image[y1:y2, x1:x2].copy(),
        [
            (crop.left, crop.top),
            (crop.right, crop.top),
            (crop.right, crop.bottom),
            (crop.left, crop.bottom),
        ],
        False,
        reliability=reliability,
        modified=not is_full,
    )


def validate_profile_crop(image: Image, crop: Crop, config: SlideConfig) -> tuple[bool, str | None]:
    """Verify a saved channel crop profile still fits this frame's layout."""
    height, width = image.shape[:2]
    area = (crop.right - crop.left) * (crop.bottom - crop.top)
    if area < 0.30:
        return False, "Saved channel crop covers too little of the frame; full frame retained."
    if config.profile_reference_aspect is not None:
        aspect = width / max(1, height)
        if abs(aspect - config.profile_reference_aspect) / config.profile_reference_aspect > 0.15:
            return False, "Video aspect ratio changed from channel profile; full frame retained."
    x1, y1 = int(crop.left * width), int(crop.top * height)
    x2, y2 = round(crop.right * width), round(crop.bottom * height)
    roi = image[y1:y2, x1:x2]
    if roi.size == 0 or float(np.std(roi)) < 6.0:
        return False, "Saved channel crop region appears blank; full frame retained."
    gray_full = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges_full = cv2.Canny(gray_full, config.edge_low_threshold, config.edge_high_threshold)
    total_edges = int(np.count_nonzero(edges_full))
    if total_edges > 50:
        roi_edges = int(np.count_nonzero(edges_full[y1:y2, x1:x2]))
        if roi_edges / total_edges < config.profile_min_edge_ratio:
            return (
                False,
                "Saved channel crop excludes most board structure; full frame retained.",
            )
    return True, None


def isolate_board(image: Image, config: SlideConfig) -> Board:
    height, width = image.shape[:2]
    full = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

    if config.corners is not None:
        pixel_corners = np.array(
            [[x * (width - 1), y * (height - 1)] for x, y in config.corners], dtype=np.float32
        )
        warped = perspective(image, pixel_corners)
        return Board(
            warped,
            list(config.corners),
            False,
            reliability="manual",
            modified=True,
        )

    if config.crop is not None:
        return _apply_crop(image, config.crop, "manual")

    if config.profile_crop is not None:
        valid, warning = validate_profile_crop(image, config.profile_crop, config)
        if valid:
            return _apply_crop(image, config.profile_crop, "profile_validated")
        return Board(
            image.copy(),
            full,
            True,
            warning,
            reliability="full_frame_fallback",
            modified=False,
        )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, config.edge_low_threshold, config.edge_high_threshold)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
    for edge_map in (edges, closed):
        contours, _ = cv2.findContours(edge_map, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for contour in contours:
            polygon = cv2.approxPolyDP(
                contour, config.board_polygon_epsilon * cv2.arcLength(contour, True), True
            )
            if len(polygon) != 4 or not cv2.isContourConvex(polygon):
                continue
            if cv2.contourArea(polygon) / (width * height) < config.board_min_area:
                continue
            points = order_corners(polygon)
            normalized = points / np.array([width, height])
            # A large inner PPT panel is not evidence that content outside it is irrelevant.
            if np.max(np.abs(normalized - np.array(full))) > config.board_border_margin:
                continue
            candidates.append(points)
        if len(candidates) == 1:
            points = candidates[0]
            return Board(
                perspective(image, points),
                [(float(x / width), float(y / height)) for x, y in points],
                False,
                reliability="auto_detected",
                modified=True,
            )

    return Board(
        image.copy(),
        full,
        True,
        "Board boundary uncertain; full frame retained.",
        reliability="full_frame_fallback",
        modified=False,
    )
