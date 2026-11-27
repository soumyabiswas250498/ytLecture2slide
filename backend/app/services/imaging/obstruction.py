"""Foreground hypotheses, explicitly not a semantic teacher detector."""

import cv2
import numpy as np

from app.domain.slides import SlideConfig
from app.services.imaging.board import Image


def large_components(mask: Image, config: SlideConfig) -> Image:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    result = np.zeros_like(mask)
    area = mask.size
    for index in range(1, count):
        fraction = stats[index, cv2.CC_STAT_AREA] / area
        if config.foreground_min_area <= fraction <= config.foreground_max_area:
            component = (labels == index).astype(np.uint8) * 255
            contours, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            # Texture inside clothing is still foreground. Fill holes rather than treating
            # matching pixels within a silhouette as proof that the board was visible.
            cv2.drawContours(result, contours, -1, 255, cv2.FILLED)
            x, y, width, height, _ = stats[index]
            if height >= mask.shape[0] * 0.2 and y + height >= mask.shape[0] * 0.75:
                padding = round(mask.shape[1] * config.foreground_padding)
                result[
                    max(0, y - padding) : min(mask.shape[0], y + height + padding),
                    max(0, x - padding) : min(mask.shape[1], x + width + padding),
                ] = 255
    if config.mask_dilation_pixels:
        size = config.mask_dilation_pixels * 2 + 1
        result = cv2.dilate(result, np.ones((size, size), dtype=np.uint8)).astype(np.uint8)
    return result


def obstruction_masks(images: list[Image], config: SlideConfig) -> list[Image]:
    if not images:
        return []
    # MOG2 measures temporal novelty, not unobstructedness. Do not trust its first-frame mask.
    model = cv2.createBackgroundSubtractorMOG2(
        history=max(10, len(images) * 2), varThreshold=config.pixel_difference, detectShadows=False
    )
    temporal = []
    for image in images:
        temporal.append(model.apply(image))
    masks = []
    median = np.median(np.stack(images), axis=0).astype(np.uint8) if len(images) >= 3 else None
    kernel = np.ones((5, 5), dtype=np.uint8)
    for index, image in enumerate(images):
        skin = cv2.inRange(
            cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb),
            np.array([0, 133, 77], dtype=np.uint8),
            np.array([255, 173, 127], dtype=np.uint8),
        )
        # Skin is a foreground hypothesis, including stationary obstruction, not semantic evidence.
        skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, kernel)
        hint = large_components(skin.astype(np.uint8), config)
        if len(images) > 1:
            delta = np.max(
                cv2.absdiff(
                    image, median if median is not None else images[(index + 1) % len(images)]
                ),
                axis=2,
            )
            motion = cv2.morphologyEx(
                (delta > config.pixel_difference).astype(np.uint8) * 255, cv2.MORPH_CLOSE, kernel
            )
            motion = large_components(motion.astype(np.uint8), config)
            if index > 0 and median is None:
                motion = cv2.bitwise_and(motion, temporal[index])
            hint = cv2.bitwise_or(hint, motion).astype(np.uint8)
        masks.append(hint)
    return masks
