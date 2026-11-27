"""Conservative board geometry and perspective correction."""

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from app.domain.slides import SlideConfig, SlideError

Image = NDArray[np.uint8]


@dataclass
class Board:
    image: Image
    coordinates: list[tuple[float, float]]
    fallback: bool
    warning: str | None = None


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


def isolate_board(image: Image, config: SlideConfig) -> Board:
    height, width = image.shape[:2]
    full = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    if config.crop:
        crop = config.crop
        x1, y1 = int(crop.left * width), int(crop.top * height)
        x2, y2 = round(crop.right * width), round(crop.bottom * height)
        if x2 - x1 < 2 or y2 - y1 < 2:
            raise SlideError("Crop is too small for this image.")
        return Board(
            image[y1:y2, x1:x2].copy(),
            [
                (crop.left, crop.top),
                (crop.right, crop.top),
                (crop.right, crop.bottom),
                (crop.left, crop.bottom),
            ],
            False,
        )
    edges = cv2.Canny(
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
        config.edge_low_threshold,
        config.edge_high_threshold,
    )
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
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
        )
    return Board(image.copy(), full, True, "Board boundary uncertain; full frame retained.")
