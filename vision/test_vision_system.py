#!/usr/bin/env python3
"""比赛视觉系统一键验收：环境、相机、ROI、模型和分类结果。"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import joblib
import numpy as np
import yaml

from run_box_vision import analyze, capture_best, open_camera


def parse_expected(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    result: dict[str, str] = {}
    for item in raw.split(","):
        key, separator, value = item.strip().partition("=")
        if not separator or key not in {"left", "center", "right"} or not value:
            raise ValueError("--expect 格式应为 left=mung_bean,center=soybean,right=white_bean")
        result[key] = value
    return result


def load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在：{path}")
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for section in ("camera", "boxes"):
        if section not in config:
            raise ValueError(f"配置缺少 {section}")
    for name in ("left", "center", "right"):
        box = config["boxes"].get(name)
        if not box or any(int(box.get(key, 0)) <= 0 for key in ("w", "h")):
            raise ValueError(f"ROI {name} 未标定；请先运行 calibrate_rois.py")
    return config


def save_results(frame: np.ndarray, annotated: np.ndarray, result: dict[str, Any], output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = output_dir / f"test_scene_{stamp}.jpg"
    debug_path = output_dir / f"test_debug_{stamp}.jpg"
    json_path = output_dir / f"test_result_{stamp}.json"
    cv2.imwrite(str(raw_path), frame)
    cv2.imwrite(str(debug_path), annotated)
    result["raw_image"] = str(raw_path)
    result["debug_image"] = str(debug_path)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw_path, debug_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="比赛视觉系统完整测试")
    parser.add_argument("--config", default="config/boxes.yaml")
    parser.add_argument("--model", default="models/bean_classifier.joblib")
    parser.add_argument("--image", help="离线测试图片；省略时从固定相机采集")
    parser.add_argument("--output-dir", default="output/system_test")
    parser.add_argument("--expect", help="期望类别，如 left=mung_bean,center=soybean,right=white_bean")
    parser.add_argument("--min-confidence", type=float, default=0.70, help="验收所需的最低置信度")
    args = parser.parse_args()
    expected = parse_expected(args.expect)
    config = load_config(Path(args.config))
    model_path = Path(args.model)
    if not model_path.is_file():
        raise FileNotFoundError(f"模型不存在：{model_path}")
    payload = joblib.load(model_path)
    if "model" not in payload:
        raise ValueError("模型文件格式错误：缺少 model")

    source = args.image or config["camera"]["device"]
    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            raise FileNotFoundError(f"无法读取离线图片：{args.image}")
    else:
        cap = open_camera(config)
        try:
            frame = capture_best(cap, int(config["camera"].get("burst_frames", 5)))
        finally:
            cap.release()

    result, annotated = analyze(frame, config, payload)
    result["test"] = {
        "source": source,
        "python": platform.python_version(),
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "model_classes": list(payload["model"].classes_),
        "expected": expected,
        "minimum_confidence": args.min_confidence,
    }
    failures: list[str] = []
    for name, item in result["boxes"].items():
        decision = item["decision"]
        if decision["confidence"] < args.min_confidence:
            failures.append(f"{name} 置信度过低：{decision['confidence']:.3f}")
        if name in expected and decision["label"] != expected[name]:
            failures.append(f"{name} 期望 {expected[name]}，实际 {decision['label']}")
    raw_path, debug_path, json_path = save_results(frame, annotated, result, Path(args.output_dir))

    print("=== 视觉系统测试结果 ===")
    print(f"图像来源：{source}")
    print(f"依赖：OpenCV {cv2.__version__}，NumPy {np.__version__}")
    for name, item in result["boxes"].items():
        decision = item["decision"]
        print(f"{name}: {decision['label']}，置信度 {decision['confidence']:.3f}")
    print(f"原图：{raw_path}")
    print(f"调试图：{debug_path}")
    print(f"JSON：{json_path}")
    if failures:
        print("测试失败：" + "；".join(failures), file=sys.stderr)
        return 2
    print("测试通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
