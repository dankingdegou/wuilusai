#!/usr/bin/env python3
"""交互式视觉标定拍照入口，行为与 capture_orbbec_rgb.py 完全一致。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    source = project_root / "capture_orbbec_rgb.py"
    if not source.is_file():
        raise SystemExit(f"未找到通用拍照脚本：{source}")

    # 默认值置于用户参数前：用户仍可在命令末尾显式覆盖任意参数。
    defaults = [
        "--width", "1280",
        "--height", "960",
        "--fps", "30",
        "--output-dir", str(Path(__file__).resolve().parent / "data" / "calibration"),
    ]
    os.execv(sys.executable, [sys.executable, str(source), *defaults, *sys.argv[1:]])


if __name__ == "__main__":
    main()
