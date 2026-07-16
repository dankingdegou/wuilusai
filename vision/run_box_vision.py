#!/usr/bin/env python3
"""固定场景三箱豆类视觉：采集、ROI、Lab 特征、类别原型决策和调试输出。"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from feature_model import extract_features


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def open_camera(config: dict[str, Any]) -> cv2.VideoCapture:
    camera = config["camera"]
    device = camera["device"] if Path(camera["device"]).exists() else camera["fallback_device"]
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开相机：{device}")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(camera["width"]))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(camera["height"]))
    cap.set(cv2.CAP_PROP_FPS, float(camera["fps"]))
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    for _ in range(int(camera.get("warmup_frames", 20))):
        cap.read()
    return cap


def sharpness(frame: np.ndarray) -> float:
    return float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def capture_best(cap: cv2.VideoCapture, count: int) -> np.ndarray:
    candidates: list[tuple[float, np.ndarray]] = []
    for _ in range(max(1, count)):
        ok, frame = cap.read()
        if ok and frame is not None:
            candidates.append((sharpness(frame), frame))
    if not candidates:
        raise RuntimeError("未能从相机读取图像")
    return max(candidates, key=lambda item: item[0])[1]


def validate_boxes(boxes: dict[str, Any], width: int, height: int) -> None:
    for name in ("left", "center", "right"):
        box = boxes.get(name, {})
        x, y, w, h = (int(box.get(key, 0)) for key in ("x", "y", "w", "h"))
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
            raise ValueError(f"ROI {name} 无效；请先执行 calibrate_rois.py 标定。")


def normalize_for_debug(bgr: np.ndarray) -> np.ndarray:
    """仅用于生成调试图，分类始终使用原始 Lab 色度，避免 CLAHE 改变类别颜色。"""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def roi_features(roi: np.ndarray) -> dict[str, float]:
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB).astype(np.float32)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV).astype(np.float32)
    # 中位数对高光、小面积阴影和少量背景更稳健。
    return {
        "L": round(float(np.median(lab[:, :, 0])), 3),
        "a": round(float(np.median(lab[:, :, 1])), 3),
        "b": round(float(np.median(lab[:, :, 2])), 3),
        "std_L": round(float(np.std(lab[:, :, 0])), 3),
        "saturation": round(float(np.median(hsv[:, :, 1])), 3),
    }


def classify(feature: dict[str, float], prototypes: dict[str, Any], minimum: float) -> dict[str, Any]:
    if not prototypes:
        return {"label": "unconfigured", "confidence": 0.0, "distance": None}
    point = np.array([feature["L"], feature["a"], feature["b"]], dtype=np.float32)
    scored = []
    for label, prototype in prototypes.items():
        reference = np.asarray(prototype["lab"], dtype=np.float32)
        distance = float(np.linalg.norm(point - reference))
        maximum = float(prototype.get("max_distance", 20.0))
        confidence = max(0.0, 1.0 - distance / maximum)
        scored.append((label, distance, confidence))
    label, distance, confidence = min(scored, key=lambda item: item[1])
    if confidence < minimum:
        label = "unknown"
    return {"label": label, "confidence": round(confidence, 3), "distance": round(distance, 3)}


def classify_with_model(roi: np.ndarray, payload: dict[str, Any]) -> dict[str, Any]:
    probabilities = payload["model"].predict_proba(extract_features(roi).reshape(1, -1))[0]
    index = int(np.argmax(probabilities))
    return {"label": str(payload["model"].classes_[index]), "confidence": round(float(probabilities[index]), 3), "distance": None}


def analyze(frame: np.ndarray, config: dict[str, Any], model_payload: dict[str, Any] | None = None) -> tuple[dict[str, Any], np.ndarray]:
    height, width = frame.shape[:2]
    boxes = config.get("boxes", {})
    validate_boxes(boxes, width, height)
    output: dict[str, Any] = {"image_size": {"width": width, "height": height}, "boxes": {}}
    annotated = frame.copy()
    for name, box in boxes.items():
        x, y, w, h = (int(box[key]) for key in ("x", "y", "w", "h"))
        roi = frame[y:y + h, x:x + w]
        feature = roi_features(roi)
        decision = (classify_with_model(roi, model_payload) if model_payload else classify(feature, config.get("prototypes", {}), config.get("decision", {}).get("minimum_confidence", 0.65)))
        output["boxes"][name] = {"roi": {"x": x, "y": y, "w": w, "h": h}, "features": feature, "decision": decision}
        color = (0, 200, 0) if decision["label"] not in {"unknown", "unconfigured"} else (0, 165, 255)
        cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
        cv2.putText(annotated, f"{name}: {decision['label']} ({decision['confidence']:.2f})", (x, max(25, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
    return output, annotated


def main() -> int:
    parser = argparse.ArgumentParser(description="运行三箱豆类视觉第一版")
    parser.add_argument("--config", default="config/boxes.yaml")
    parser.add_argument("--image", help="离线图片；未指定时从相机采集")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--model", help="训练好的 joblib 模型；省略时回退到 Lab 原型")
    args = parser.parse_args()
    config = load_config(Path(args.config))
    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            raise SystemExit(f"无法读取：{args.image}")
    else:
        cap = open_camera(config)
        try:
            frame = capture_best(cap, int(config["camera"].get("burst_frames", 5)))
        finally:
            cap.release()
    model_payload = None
    if args.model:
        import joblib
        model_payload = joblib.load(args.model)
    result, annotated = analyze(frame, config, model_payload)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / f"scene_{stamp}.jpg"
    debug_path = output_dir / f"debug_{stamp}.jpg"
    json_path = output_dir / f"result_{stamp}.json"
    cv2.imwrite(str(raw_path), frame)
    cv2.imwrite(str(debug_path), normalize_for_debug(annotated))
    result.update({"timestamp": time.time(), "raw_image": str(raw_path), "debug_image": str(debug_path)})
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"调试图：{debug_path}\n结果：{json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
