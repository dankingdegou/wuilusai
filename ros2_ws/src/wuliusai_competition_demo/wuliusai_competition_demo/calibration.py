from __future__ import annotations

from typing import Any

import cv2
import numpy as np


WORLD_CORNERS_ORDER = ("bottom_left", "bottom_right", "top_right", "top_left")


def image_corners_from_config(config: dict[str, Any]) -> np.ndarray:
    points = config.get("field", {}).get("image_corners_px", [])
    if not isinstance(points, list) or len(points) != 4:
        raise ValueError("field.image_corners_px must contain four clicked points")
    array = np.asarray(points, dtype=np.float32)
    if array.shape != (4, 2):
        raise ValueError("field.image_corners_px must be [[u,v], ...] in BL,BR,TR,TL order")
    if abs(cv2.contourArea(array.reshape(-1, 1, 2))) < 100.0:
        raise ValueError("field corner polygon is degenerate")
    return array


def field_homography(config: dict[str, Any]) -> np.ndarray:
    source = image_corners_from_config(config)
    field = config.get("field", {})
    width, height = float(field.get("width_mm", 0)), float(field.get("height_mm", 0))
    if width <= 0 or height <= 0:
        raise ValueError("field width_mm and height_mm must be positive")
    destination = np.asarray([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
    return cv2.getPerspectiveTransform(source, destination)


def pixel_to_world(point_px: tuple[float, float], homography: np.ndarray) -> tuple[float, float]:
    point = np.asarray([[[float(point_px[0]), float(point_px[1])]]], dtype=np.float32)
    converted = cv2.perspectiveTransform(point, homography)[0, 0]
    return float(converted[0]), float(converted[1])


def valid_waypoint(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        point = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    return point if all(np.isfinite(point)) else None


def within_field(point: tuple[float, float], config: dict[str, Any], margin_mm: float = 0.0) -> bool:
    field = config["field"]
    return (margin_mm <= point[0] <= float(field["width_mm"]) - margin_mm and
            margin_mm <= point[1] <= float(field["height_mm"]) - margin_mm)
