#!/usr/bin/env bash
# Jetson Orin NX 相机拍照启动器。
set -euo pipefail

ROOT="$HOME/wuliusai_competition"
ENV_PYTHON="$ROOT/.venv-camera/bin/python"
CAPTURE_SCRIPT="$ROOT/scripts/capture_orbbec_rgb.py"

if [[ ! -x "$ENV_PYTHON" || ! -f "$CAPTURE_SCRIPT" ]]; then
    echo "相机环境或拍照脚本不存在：$ROOT" >&2
    exit 1
fi

# -s 禁用用户 site-packages，确保 OpenCV 使用系统兼容的 NumPy 1.x。
exec "$ENV_PYTHON" -s "$CAPTURE_SCRIPT" "$@"
