#!/usr/bin/env bash
# Start only the gantry stepper ROS 2 node. It sends no motion until an Action goal arrives.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/jetson_env.sh"

if [[ ! -e /dev/stepper_controller ]]; then
  echo 'ERROR: /dev/stepper_controller is missing. Connect the STM32 USB CDC cable and install its udev rule first.' >&2
  exit 1
fi

exec ros2 launch wuliusai_stepper_controller stepper_controller.launch.py
