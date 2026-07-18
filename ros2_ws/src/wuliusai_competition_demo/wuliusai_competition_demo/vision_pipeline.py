"""Fixed-scene source recognition and dense single-scoop point selection."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from .calibration import field_homography, pixel_to_world, within_field


SUPPORTED_BEANS = {"mung_bean", "soybean", "white_bean"}


def _features(roi: np.ndarray) -> np.ndarray:
    lab, hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB), cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    values: list[float] = []
    for image in (lab, hsv):
        for channel in range(3):
            data = image[:, :, channel].astype(np.float32)
            values.extend(np.percentile(data, [5, 15, 25, 50, 75, 85, 95]).tolist())
            values.extend([float(data.mean()), float(data.std())])
    histogram = cv2.calcHist([lab], [1, 2], None, [8, 8], [0, 256, 0, 256]).ravel()
    values.extend((histogram / max(float(histogram.sum()), 1.0)).tolist())
    return np.asarray(values, dtype=np.float32)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


class ScoopVision:
    def __init__(self, config: dict[str, Any], config_path: Path) -> None:
        self.config, self.config_path = config, config_path
        vision = config.get("vision", {})
        self.minimum_confidence = float(vision.get("minimum_confidence", 0.80))
        self.retries = max(0, int(vision.get("retries", 2)))
        self.radius = max(5, int(vision.get("scoop_radius_px", 45)))
        self.margin = max(1, int(vision.get("border_margin_px", 25)))
        self.minimum_foreground_ratio = float(vision.get("minimum_foreground_ratio", 0.02))
        self.homography = field_homography(config)
        raw_path = str(vision.get("config_file", ""))
        if not raw_path:
            raise ValueError("vision.config_file is required")
        self.vision_config_path = self._resolve(raw_path)
        self.camera_config = _load_yaml(self.vision_config_path)
        self.model_payload = self._load_model(str(vision.get("model_file", "")))

    def _resolve(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        return path if path.is_absolute() else (self.config_path.parent / path).resolve()

    def _load_model(self, raw_path: str) -> dict[str, Any] | None:
        if not raw_path:
            return None
        path = self._resolve(raw_path)
        if not path.exists():
            raise ValueError(f"vision model not found: {path}")
        try:
            import joblib
        except ImportError as exc:
            raise RuntimeError("model configured but Python joblib is not installed") from exc
        payload = joblib.load(path)
        if not isinstance(payload, dict) or "model" not in payload:
            raise ValueError("vision model must be the bean_classifier joblib payload")
        return payload

    def _open_camera(self) -> cv2.VideoCapture:
        camera = self.camera_config.get("camera", {})
        primary, fallback = str(camera.get("device", "")), str(camera.get("fallback_device", "/dev/video0"))
        device = primary if primary and Path(primary).exists() else fallback
        cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError(f"cannot open camera: {device}")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(camera.get("width", 1280)))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(camera.get("height", 960)))
        cap.set(cv2.CAP_PROP_FPS, float(camera.get("fps", 30)))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        for _ in range(int(camera.get("warmup_frames", 20))):
            cap.read()
        return cap

    @staticmethod
    def _sharpness(frame: np.ndarray) -> float:
        return float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())

    def capture(self) -> np.ndarray:
        cap = self._open_camera()
        try:
            candidates: list[tuple[float, np.ndarray]] = []
            count = max(1, int(self.camera_config.get("camera", {}).get("burst_frames", 5)))
            for _ in range(count):
                ok, frame = cap.read()
                if ok and frame is not None:
                    candidates.append((self._sharpness(frame), frame))
            if not candidates:
                raise RuntimeError("camera returned no frame")
            return max(candidates, key=lambda item: item[0])[1]
        finally:
            cap.release()

    @staticmethod
    def _valid_boxes(boxes: dict[str, Any], frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        if not boxes:
            raise ValueError("no vision boxes configured")
        for name, box in boxes.items():
            x, y, w, h = (int(box.get(key, 0)) for key in ("x", "y", "w", "h"))
            if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
                raise ValueError(f"invalid vision ROI: {name}; calibrate boxes first")

    def _classify(self, roi: np.ndarray) -> tuple[str, float]:
        if self.model_payload is not None:
            model = self.model_payload["model"]
            probabilities = model.predict_proba(_features(roi).reshape(1, -1))[0]
            index = int(np.argmax(probabilities))
            return str(model.classes_[index]), float(probabilities[index])
        prototypes = self.camera_config.get("prototypes", {})
        if not prototypes:
            return "unknown", 0.0
        point = np.median(cv2.cvtColor(roi, cv2.COLOR_BGR2LAB).reshape(-1, 3), axis=0)
        candidates = []
        for label, item in prototypes.items():
            distance = float(np.linalg.norm(point - np.asarray(item["lab"], dtype=np.float32)))
            confidence = max(0.0, 1.0 - distance / float(item.get("max_distance", 20.0)))
            candidates.append((label, confidence, distance))
        label, confidence, _ = min(candidates, key=lambda row: row[2])
        return label, confidence

    def _foreground_mask(self, roi: np.ndarray) -> np.ndarray:
        """Segment contents by distance from the surrounding box floor/border.

        This is intentionally adaptive: no fixed bean colour threshold is used.
        The source box border supplies a local background reference each capture.
        """
        h, w = roi.shape[:2]
        band = max(3, min(15, min(h, w) // 12))
        border = np.concatenate((roi[:band].reshape(-1, 3), roi[-band:].reshape(-1, 3),
                                 roi[:, :band].reshape(-1, 3), roi[:, -band:].reshape(-1, 3)))
        lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB).astype(np.float32)
        background = np.median(cv2.cvtColor(border.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB).reshape(-1, 3), axis=0)
        distance = np.clip(np.linalg.norm(lab - background, axis=2), 0, 255).astype(np.uint8)
        _, mask = cv2.threshold(distance, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask[:self.margin] = 0; mask[-self.margin:] = 0
        mask[:, :self.margin] = 0; mask[:, -self.margin:] = 0
        return mask

    def _scoop_pixel(self, roi: np.ndarray) -> tuple[tuple[int, int], float, np.ndarray]:
        mask = self._foreground_mask(roi)
        ratio = float(np.count_nonzero(mask)) / float(mask.size)
        if ratio < self.minimum_foreground_ratio:
            raise RuntimeError(f"foreground ratio {ratio:.3f} below safety threshold")
        radius = min(self.radius, max(5, min(roi.shape[:2]) // 4))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
        density = cv2.filter2D((mask > 0).astype(np.float32), -1, kernel / max(float(kernel.sum()), 1.0))
        density[:radius] = 0; density[-radius:] = 0
        density[:, :radius] = 0; density[:, -radius:] = 0
        _, peak, _, location = cv2.minMaxLoc(density)
        if peak <= 0.0:
            raise RuntimeError("no safe scoop region found")
        return (int(location[0]), int(location[1])), float(peak), mask

    def plan(self, bean_type: str) -> dict[str, Any]:
        if bean_type not in SUPPORTED_BEANS:
            raise ValueError(f"unsupported bean_type: {bean_type}")
        last_error = "vision did not run"
        for attempt in range(self.retries + 1):
            try:
                frame = self.capture()
                boxes = self.camera_config.get("boxes", {})
                self._valid_boxes(boxes, frame)
                matches: list[tuple[str, dict[str, Any], float]] = []
                for name, box in boxes.items():
                    x, y, w, h = (int(box[key]) for key in ("x", "y", "w", "h"))
                    label, confidence = self._classify(frame[y:y + h, x:x + w])
                    if label == bean_type and confidence >= self.minimum_confidence:
                        matches.append((name, box, confidence))
                if not matches:
                    raise RuntimeError(f"{bean_type} not recognised with confidence >= {self.minimum_confidence:.2f}")
                name, box, confidence = max(matches, key=lambda item: item[2])
                x, y, w, h = (int(box[key]) for key in ("x", "y", "w", "h"))
                (u, v), density, mask = self._scoop_pixel(frame[y:y + h, x:x + w])
                pixel = (x + u, y + v)
                world = pixel_to_world(pixel, self.homography)
                if not within_field(world, self.config, margin_mm=0.0):
                    raise RuntimeError(f"scoop point outside field: {world}")
                return {"attempt": attempt + 1, "box": name, "confidence": confidence,
                        "density": density, "pixel": pixel, "world": world, "frame": frame, "mask": mask,
                        "roi": (x, y, w, h)}
            except Exception as exc:
                last_error = str(exc)
        raise RuntimeError(f"vision failed after {self.retries + 1} captures: {last_error}")
