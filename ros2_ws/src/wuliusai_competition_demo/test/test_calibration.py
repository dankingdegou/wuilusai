import numpy as np
import cv2

from wuliusai_competition_demo.calibration import field_homography, pixel_to_world, valid_waypoint
from wuliusai_competition_demo.vision_pipeline import ScoopVision


def test_rectangular_field_homography():
    config = {"field": {"width_mm": 4000, "height_mm": 2000,
                        "image_corners_px": [[100, 900], [1100, 900], [1100, 100], [100, 100]]}}
    transform = field_homography(config)
    assert np.allclose(pixel_to_world((100, 900), transform), (0, 0), atol=0.01)
    assert np.allclose(pixel_to_world((1100, 100), transform), (4000, 2000), atol=0.01)


def test_invalid_waypoints_are_rejected():
    assert valid_waypoint([]) is None
    assert valid_waypoint([1]) is None
    assert valid_waypoint([100.0, 200.0]) == (100.0, 200.0)


def test_scoop_point_prefers_dense_interior_region():
    vision = ScoopVision.__new__(ScoopVision)
    vision.margin, vision.radius, vision.minimum_foreground_ratio = 12, 14, 0.01
    # Pale box floor with a dense, coloured bean patch near (75, 65).
    roi = np.full((120, 140, 3), (200, 200, 200), dtype=np.uint8)
    cv2.circle(roi, (75, 65), 26, (40, 120, 50), -1)
    pixel, density, mask = vision._scoop_pixel(roi)
    assert 55 < pixel[0] < 95 and 45 < pixel[1] < 85
    assert density > 0.5
    assert mask[0, 0] == 0
