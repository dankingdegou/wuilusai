#!/usr/bin/env bash
# Start the competition Action server with the STM32 USB-CDC / X-gantry stack.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /absolute/path/to/competition_demo.yaml" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/jetson_env.sh"

if [[ ! -e /dev/stepper_controller ]]; then
  echo 'ERROR: /dev/stepper_controller is missing; check the STM32 USB CDC cable and udev rule.' >&2
  exit 1
fi
if [[ ! -f "$1" ]]; then
  echo "ERROR: configuration file not found: $1" >&2
  exit 1
fi

exec ros2 launch wuliusai_competition_demo competition_demo.launch.py config:="$1"
