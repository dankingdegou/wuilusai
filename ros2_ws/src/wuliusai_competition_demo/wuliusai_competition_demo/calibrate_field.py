"""Click the four competition-field corners and save the pixel calibration."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import yaml


ORDER = ("bottom_left", "bottom_right", "top_right", "top_left")


def main() -> None:
    parser = argparse.ArgumentParser(description="标定比赛场地四个角：左下、右下、右上、左上")
    parser.add_argument("--image", required=True, help="固定相机拍摄的完整场地图")
    parser.add_argument("--config", required=True, help="competition_demo.yaml")
    args = parser.parse_args()
    image = cv2.imread(args.image)
    if image is None:
        raise SystemExit(f"cannot read image: {args.image}")
    points: list[tuple[int, int]] = []
    window = "field calibration: BL, BR, TR, TL | r=reset, Enter=save, Esc=cancel"

    def redraw() -> None:
        display = image.copy()
        for index, point in enumerate(points):
            cv2.circle(display, point, 7, (0, 0, 255), -1)
            cv2.putText(display, f"{index + 1}:{ORDER[index]}", (point[0] + 8, point[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
        if len(points) > 1:
            cv2.polylines(display, [np.asarray(points, dtype=np.int32)], False, (0, 255, 255), 2)
        cv2.imshow(window, display)

    def click(event, x, y, _flags, _param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((x, y)); redraw()

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, click)
    redraw()
    while True:
        key = cv2.waitKey(20) & 0xFF
        if key == 27:
            cv2.destroyAllWindows(); raise SystemExit("calibration canceled")
        if key in (ord("r"), ord("R")):
            points.clear(); redraw()
        if key in (10, 13) and len(points) == 4:
            break
    cv2.destroyAllWindows()
    config_path = Path(args.config)
    with config_path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream) or {}
    config.setdefault("field", {})["image_corners_px"] = [[x, y] for x, y in points]
    with config_path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(config, stream, allow_unicode=True, sort_keys=False)
    print(f"saved {config_path}: {dict(zip(ORDER, points))}")


if __name__ == "__main__":
    main()
