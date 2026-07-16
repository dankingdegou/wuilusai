"""豆类 ROI 的颜色分布特征；训练与在线推理必须共用本文件。"""
from __future__ import annotations

import cv2
import numpy as np


def extract_features(roi: np.ndarray) -> np.ndarray:
    """提取对局部亮度变化更稳健的 Lab / HSV 分位数和 Lab 色度直方图。"""
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    features: list[float] = []
    for image in (lab, hsv):
        for channel in range(3):
            values = image[:, :, channel].astype(np.float32)
            features.extend(np.percentile(values, [5, 15, 25, 50, 75, 85, 95]).tolist())
            features.extend([float(values.mean()), float(values.std())])
    # 仅取 Lab 的色度通道；归一化后对 ROI 大小不敏感。
    histogram = cv2.calcHist([lab], [1, 2], None, [8, 8], [0, 256, 0, 256]).ravel()
    features.extend((histogram / max(float(histogram.sum()), 1.0)).tolist())
    return np.asarray(features, dtype=np.float32)
