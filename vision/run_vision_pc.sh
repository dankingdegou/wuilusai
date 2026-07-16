#!/usr/bin/env bash
# PC 视觉推理入口，使用含 scikit-learn 的独立环境。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/.venv/bin/python" "$ROOT/run_box_vision.py" --model "$ROOT/models/bean_classifier.joblib" "$@"
