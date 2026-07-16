#!/usr/bin/env python3
"""由 data/labels.yaml 训练三类豆子分类器，并以整组留出方式验证。"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import cv2
import joblib
import numpy as np
import yaml
from sklearn.model_selection import LeaveOneGroupOut, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from feature_model import extract_features


def captured_at(filename: str) -> datetime:
    match = re.search(r"(20\d{6}_\d{6})", filename)
    if not match:
        raise ValueError(f"文件名缺少时间戳：{filename}")
    return datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")


def load_samples(config: dict, manifest: dict, images_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict], int]:
    rows, group, skipped_empty = [], 0, 0
    previous = None
    for filename in sorted(manifest["labels"], key=captured_at):
        current = captured_at(filename)
        if previous and (current - previous).total_seconds() > 4.0:
            group += 1
        previous = current
        image = cv2.imread(str(images_dir / filename))
        if image is None:
            raise FileNotFoundError(images_dir / filename)
        for box_name, label in manifest["labels"][filename].items():
            # ``empty`` is useful annotation metadata, but a few empty examples
            # are not enough to train a reliable fourth visual class. Empty-box
            # detection should be added as a dedicated occupancy check later.
            if label == "empty":
                skipped_empty += 1
                continue
            box = config["boxes"][box_name]
            roi = image[box["y"]:box["y"] + box["h"], box["x"]:box["x"] + box["w"]]
            rows.append({"feature": extract_features(roi), "label": label, "group": group, "filename": filename, "box": box_name})
    return (np.vstack([row["feature"] for row in rows]), np.asarray([row["label"] for row in rows]), np.asarray([row["group"] for row in rows]), rows, skipped_empty)


def main() -> int:
    parser = argparse.ArgumentParser(description="训练并验证比赛豆类分类器")
    parser.add_argument("--config", default="config/boxes.yaml")
    parser.add_argument("--labels", default="data/labels.yaml")
    parser.add_argument("--images-dir", default="data/calibration")
    parser.add_argument("--model", default="models/bean_classifier.joblib")
    parser.add_argument("--report", default="output/cross_validation.json")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    manifest = yaml.safe_load(Path(args.labels).read_text(encoding="utf-8"))
    features, labels, groups, rows, skipped_empty = load_samples(config, manifest, Path(args.images_dir))
    model = make_pipeline(StandardScaler(), SVC(C=4.0, gamma="scale", probability=True, random_state=42))
    prediction = cross_val_predict(model, features, labels, groups=groups, cv=LeaveOneGroupOut())
    errors = [
        {"image": row["filename"], "box": row["box"], "expected": expected, "predicted": predicted}
        for row, expected, predicted in zip(rows, labels, prediction)
        if expected != predicted
    ]
    report = {
        "validation": "LeaveOneGroupOut：每次留出一整组不同摆放位置的照片",
        "samples": int(len(labels)),
        "skipped_empty_samples": skipped_empty,
        "groups": int(len(np.unique(groups))),
        "correct": int(np.sum(prediction == labels)),
        "accuracy": round(float(np.mean(prediction == labels)), 4),
        "errors": errors,
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    model.fit(features, labels)
    Path(args.model).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "classes": manifest["classes"], "feature_version": 1}, args.model)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"模型：{args.model}\n验证报告：{args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
