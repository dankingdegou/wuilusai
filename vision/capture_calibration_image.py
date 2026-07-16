#!/usr/bin/env python3
"""为三箱视觉标定拍摄一张固定分辨率的清晰图片。"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import cv2


DEFAULT_DEVICE = (
    "/dev/v4l/by-id/"
    "usb-Sonix_Technology_Co.__Ltd._USB_2.0_Camera_SN0001-video-index0"
)


def sharpness(frame) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def main() -> int:
    parser = argparse.ArgumentParser(description="拍摄比赛三箱 ROI 标定图")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="固定相机设备路径")
    parser.add_argument("--width", type=int, default=1280, help="输出宽度")
    parser.add_argument("--height", type=int, default=960, help="输出高度")
    parser.add_argument("--fps", type=float, default=30.0, help="目标帧率")
    parser.add_argument("--warmup", type=int, default=30, help="预热丢弃帧数")
    parser.add_argument("--burst", type=int, default=5, help="连拍帧数，自动选最清晰一张")
    parser.add_argument("--output-dir", default="data/calibration", help="保存目录")
    args = parser.parse_args()

    device = args.device if Path(args.device).exists() else "/dev/video2"
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise SystemExit(f"无法打开相机：{device}")
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        cap.set(cv2.CAP_PROP_FPS, args.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        for _ in range(max(0, args.warmup)):
            cap.read()
        frames = []
        for _ in range(max(1, args.burst)):
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
        if not frames:
            raise SystemExit("相机已打开，但没有读到画面。")
        image = max(frames, key=sharpness)
        height, width = image.shape[:2]
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"calibration_{datetime.now():%Y%m%d_%H%M%S}_{width}x{height}.jpg"
        if not cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 100]):
            raise SystemExit(f"保存失败：{path}")
        print(f"设备：{device}")
        print(f"实际分辨率：{width} × {height}")
        print(f"清晰度评分：{sharpness(image):.2f}")
        print(f"已保存：{path.resolve()}")
        return 0
    finally:
        cap.release()


if __name__ == "__main__":
    raise SystemExit(main())
