#!/usr/bin/env python3
"""在一张比赛场景照片上，依次框选 left、center、right 三个箱子 ROI。"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="标定三个固定箱子的 ROI")
    parser.add_argument("--image", required=True, help="相机拍摄的场景照片")
    parser.add_argument("--config", default="config/boxes.yaml", help="要写入的 YAML 配置")
    args = parser.parse_args()

    image = cv2.imread(args.image)
    if image is None:
        raise SystemExit(f"无法读取图片：{args.image}")
    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"配置不存在：{config_path}；请先复制 boxes.example.yaml")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    boxes = {}
    for name in ("left", "center", "right"):
        print(f"框选 {name} 箱子的内部区域，确认后按 Enter / Space，取消按 C。")
        x, y, w, h = cv2.selectROI(f"ROI: {name}", image, showCrosshair=True)
        if w <= 0 or h <= 0:
            cv2.destroyAllWindows()
            raise SystemExit(f"{name} ROI 未完成，配置未写入。")
        boxes[name] = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
    cv2.destroyAllWindows()
    config["boxes"] = boxes
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"已写入：{config_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
