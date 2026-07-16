#!/usr/bin/env python3
"""根据已标注照片生成鲁棒 Lab 颜色原型，并更新 boxes.yaml。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import yaml

from run_box_vision import roi_features


def main() -> int:
    parser = argparse.ArgumentParser(description="从已标注数据建立 Lab 类别原型")
    parser.add_argument("--config", default="config/boxes.yaml")
    parser.add_argument("--labels", default="data/labels.yaml")
    parser.add_argument("--images-dir", default="data/calibration")
    parser.add_argument("--report", default="output/prototype_report.json")
    args = parser.parse_args()
    config_path, labels_path = Path(args.config), Path(args.labels)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    manifest = yaml.safe_load(labels_path.read_text(encoding="utf-8"))
    samples: dict[str, list[np.ndarray]] = {name: [] for name in manifest["classes"]}
    for filename, assignments in manifest.get("labels", {}).items():
        image = cv2.imread(str(Path(args.images_dir) / filename))
        if image is None:
            continue
        for box_name, label in assignments.items():
            if label not in samples:
                continue
            box = config["boxes"][box_name]
            roi = image[box["y"]:box["y"] + box["h"], box["x"]:box["x"] + box["w"]]
            feature = roi_features(roi)
            samples[label].append(np.array([feature["L"], feature["a"], feature["b"]], dtype=float))
    prototypes, report = {}, {}
    for label, values in samples.items():
        if len(values) < 3:
            raise SystemExit(f"类别 {label} 的有效样本不足 3 个，当前为 {len(values)}。")
        matrix = np.vstack(values)
        center = np.median(matrix, axis=0)
        distances = np.linalg.norm(matrix - center, axis=1)
        # 95% 分位距离加 15% 裕量；现场分类仍受 minimum_confidence 约束。
        maximum = max(8.0, float(np.quantile(distances, 0.95) * 1.15))
        prototypes[label] = {"lab": [round(float(value), 3) for value in center], "max_distance": round(maximum, 3)}
        report[label] = {"count": len(values), "median_lab": prototypes[label]["lab"], "max_distance": prototypes[label]["max_distance"], "distance_p95": round(float(np.quantile(distances, 0.95)), 3)}
    config["prototypes"] = prototypes
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"已更新：{config_path}\n报告：{report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
