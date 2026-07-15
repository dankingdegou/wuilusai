#!/usr/bin/env bash
# Read-only verification: this script never sends a servo or motor command.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/jetson_env.sh"

echo '=== Stable aliases ==='
for device in /dev/ros_robot_controller /dev/stepper_controller; do
  if [[ -e "$device" ]]; then
    ls -l "$device"
    udevadm info -q property -n "$device" | grep -E '^(DEVNAME|ID_VENDOR_ID|ID_MODEL_ID|ID_SERIAL|ID_PATH)=' || true
  else
    echo "MISSING: $device"
  fi
done

echo '=== Raw serial devices ==='
ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || true

echo '=== ROS 2 packages ==='
ros2 pkg prefix ros_robot_controller
ros2 pkg prefix wuliusai_stepper_controller
echo 'Device check complete; no motion command was sent.'
