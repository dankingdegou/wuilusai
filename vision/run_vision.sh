#!/usr/bin/env bash
# Jetson 视觉模块启动器：隔离用户目录中的 NumPy 2，使用系统 OpenCV。
set -euo pipefail

ROOT="$HOME/wuliusai_competition"
PYTHON="$ROOT/.venv-camera/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "缺少相机虚拟环境：$PYTHON" >&2
    exit 1
fi

exec "$PYTHON" -s "$ROOT/vision/run_box_vision.py" "$@"
