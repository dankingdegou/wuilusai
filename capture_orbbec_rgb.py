#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Orbbec / Sonix UVC RGB 相机拍照脚本

目标采集模式：
    MJPG
    2048 × 1536
    30 FPS

功能：
1. 优先使用 /dev/v4l/by-id 下的稳定设备路径
2. 自动回退到 /dev/video2
3. 相机预热
4. 单次拍照或预览按键拍照
5. 连拍若干帧并自动选择清晰度最高的一帧
6. 使用时间戳命名，保存 JPEG
7. 输出实际分辨率、帧率和保存路径

按键模式：
    Space / Enter：拍照
    Q / Esc：退出
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


DEFAULT_BY_ID = (
    "/dev/v4l/by-id/"
    "usb-Sonix_Technology_Co.__Ltd._USB_2.0_Camera_SN0001-video-index0"
)
DEFAULT_FALLBACK = "/dev/video2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 Orbbec RGB UVC 摄像头拍摄 2048×1536 MJPG 照片"
    )
    parser.add_argument(
        "--device",
        default=DEFAULT_BY_ID,
        help=f"摄像头设备路径，默认：{DEFAULT_BY_ID}",
    )
    parser.add_argument(
        "--fallback-device",
        default=DEFAULT_FALLBACK,
        help=f"主设备不可用时的回退设备，默认：{DEFAULT_FALLBACK}",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.home() / "Pictures" / "orbbec_archive"),
        help="照片保存目录",
    )
    parser.add_argument("--width", type=int, default=2048, help="采集宽度")
    parser.add_argument("--height", type=int, default=1536, help="采集高度")
    parser.add_argument("--fps", type=float, default=30.0, help="目标帧率")
    parser.add_argument(
        "--warmup",
        type=float,
        default=2.0,
        help="相机预热时间，单位为秒",
    )
    parser.add_argument(
        "--burst",
        type=int,
        default=5,
        help="每次拍照连续读取的帧数，并选择最清晰的一帧",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=100,
        choices=range(1, 101),
        metavar="[1-100]",
        help="JPEG 保存质量，默认 100",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="预热后立即拍摄一张并退出",
    )
    parser.add_argument(
        "--no-preview-scale",
        action="store_true",
        help="预览时不缩放画面",
    )
    return parser.parse_args()


def resolve_device(primary: str, fallback: str) -> str:
    primary_path = Path(primary)
    fallback_path = Path(fallback)

    if primary_path.exists():
        return str(primary_path)

    if fallback_path.exists():
        print(
            f"[警告] 固定设备路径不存在：{primary}\n"
            f"[信息] 使用回退设备：{fallback}",
            file=sys.stderr,
        )
        return str(fallback_path)

    raise FileNotFoundError(
        "未找到摄像头设备。\n"
        f"检查过：\n  {primary}\n  {fallback}\n"
        "请先执行：v4l2-ctl --list-devices"
    )


def open_camera(
    device: str,
    width: int,
    height: int,
    fps: float,
) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)

    if not cap.isOpened():
        raise RuntimeError(
            f"无法打开摄像头：{device}\n"
            "请确认没有被 GUVCView、浏览器、OBS 或其他程序占用。"
        )

    # 设置顺序很重要：先指定 MJPG，再设置分辨率和帧率。
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    cap.set(cv2.CAP_PROP_FOURCC, fourcc)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    # 减少缓存，尽量获得最新画面。部分驱动可能忽略此设置。
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # 读取一帧，确认设置真正生效。
    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        raise RuntimeError(
            "摄像头已打开，但无法读取图像。\n"
            "建议先运行：\n"
            f"  ffplay -f v4l2 -input_format mjpeg "
            f"-video_size {width}x{height} -framerate {int(fps)} -i {device}"
        )

    return cap


def print_camera_status(cap: cv2.VideoCapture, device: str) -> None:
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    actual_fourcc_value = int(cap.get(cv2.CAP_PROP_FOURCC))
    actual_fourcc = "".join(
        chr((actual_fourcc_value >> (8 * i)) & 0xFF) for i in range(4)
    )

    print("========== 摄像头状态 ==========")
    print(f"设备：{device}")
    print(f"实际格式：{actual_fourcc}")
    print(f"实际分辨率：{actual_width} × {actual_height}")
    print(f"驱动报告帧率：{actual_fps:.2f} FPS")
    print("================================")

    if (actual_width, actual_height) != (2048, 1536):
        print(
            "[警告] 实际分辨率不是 2048×1536。"
            "请检查设备是否被其他程序占用，或驱动是否接受了设置。",
            file=sys.stderr,
        )

    if actual_fourcc.strip("\x00") != "MJPG":
        print(
            f"[警告] 实际格式为 {actual_fourcc!r}，不是 MJPG。",
            file=sys.stderr,
        )


def warm_up(cap: cv2.VideoCapture, seconds: float) -> None:
    print(f"[信息] 相机预热 {seconds:.1f} 秒...")
    deadline = time.monotonic() + max(seconds, 0.0)

    while time.monotonic() < deadline:
        ok, _ = cap.read()
        if not ok:
            raise RuntimeError("相机预热过程中读取图像失败。")


def sharpness_score(frame: np.ndarray) -> float:
    """使用拉普拉斯方差估算图像清晰度。"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def capture_best_frame(
    cap: cv2.VideoCapture,
    burst_count: int,
) -> tuple[np.ndarray, float]:
    burst_count = max(1, burst_count)
    best_frame: Optional[np.ndarray] = None
    best_score = -1.0

    # 先丢弃一帧，降低旧缓存帧的影响。
    cap.grab()

    for _ in range(burst_count):
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        score = sharpness_score(frame)
        if score > best_score:
            best_score = score
            best_frame = frame.copy()

    if best_frame is None:
        raise RuntimeError("连续读取图像失败，未获得可保存的画面。")

    return best_frame, best_score


def build_output_path(output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return output_dir / f"orbbec_{timestamp}_2048x1536.jpg"


def save_photo(
    frame: np.ndarray,
    output_dir: Path,
    jpeg_quality: int,
    sharpness: float,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = build_output_path(output_dir)

    params = [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)]
    ok = cv2.imwrite(str(output_path), frame, params)

    if not ok:
        raise RuntimeError(f"照片保存失败：{output_path}")

    height, width = frame.shape[:2]
    file_size_mb = output_path.stat().st_size / (1024 * 1024)

    print("\n[成功] 照片已保存")
    print(f"路径：{output_path}")
    print(f"分辨率：{width} × {height}")
    print(f"JPEG 质量：{jpeg_quality}")
    print(f"清晰度评分：{sharpness:.2f}")
    print(f"文件大小：{file_size_mb:.2f} MB")

    return output_path


def make_preview(frame: np.ndarray, no_scale: bool) -> np.ndarray:
    if no_scale:
        return frame

    max_width = 1280
    max_height = 900
    height, width = frame.shape[:2]

    scale = min(max_width / width, max_height / height, 1.0)
    if scale >= 1.0:
        return frame

    preview_width = int(width * scale)
    preview_height = int(height * scale)

    return cv2.resize(
        frame,
        (preview_width, preview_height),
        interpolation=cv2.INTER_AREA,
    )


def run_once(
    cap: cv2.VideoCapture,
    output_dir: Path,
    burst: int,
    jpeg_quality: int,
) -> None:
    frame, score = capture_best_frame(cap, burst)
    save_photo(frame, output_dir, jpeg_quality, score)


def run_interactive(
    cap: cv2.VideoCapture,
    output_dir: Path,
    burst: int,
    jpeg_quality: int,
    no_preview_scale: bool,
) -> None:
    window_name = "Orbbec RGB - Space/Enter拍照，Q/Esc退出"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)

    print("[操作] 按 Space 或 Enter 拍照，按 Q 或 Esc 退出。")

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            print("[警告] 当前帧读取失败，正在重试...", file=sys.stderr)
            time.sleep(0.05)
            continue

        preview = make_preview(frame, no_preview_scale)
        cv2.imshow(window_name, preview)

        key = cv2.waitKey(1) & 0xFF

        if key in (ord("q"), ord("Q"), 27):
            break

        if key in (ord(" "), 10, 13):
            best_frame, score = capture_best_frame(cap, burst)
            save_photo(best_frame, output_dir, jpeg_quality, score)


def main() -> int:
    args = parse_args()

    try:
        device = resolve_device(args.device, args.fallback_device)
        output_dir = Path(args.output_dir).expanduser().resolve()

        cap = open_camera(
            device=device,
            width=args.width,
            height=args.height,
            fps=args.fps,
        )

        try:
            print_camera_status(cap, device)
            warm_up(cap, args.warmup)

            if args.once:
                run_once(
                    cap,
                    output_dir,
                    args.burst,
                    args.jpeg_quality,
                )
            else:
                run_interactive(
                    cap,
                    output_dir,
                    args.burst,
                    args.jpeg_quality,
                    args.no_preview_scale,
                )
        finally:
            cap.release()
            cv2.destroyAllWindows()

        return 0

    except KeyboardInterrupt:
        print("\n[信息] 用户中止。")
        return 130
    except Exception as exc:
        print(f"\n[错误] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
