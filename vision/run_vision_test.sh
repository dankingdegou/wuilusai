#!/usr/bin/env bash
# PC / Jetson 通用视觉验收入口，使用仓库内独立虚拟环境。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/.venv/bin/python" "$ROOT/test_vision_system.py" "$@"
