#!/usr/bin/env bash
# Source this file before running competition ROS 2 commands on the Jetson.
set -e

source /opt/ros/humble/setup.bash
export WULIUSAI_REPO="${WULIUSAI_REPO:-$HOME/wuilusai}"
WULIUSAI_ROS_WS="${WULIUSAI_ROS_WS:-$WULIUSAI_REPO/ros2_ws}"
if [[ -f "$WULIUSAI_ROS_WS/install/setup.bash" ]]; then
  source "$WULIUSAI_ROS_WS/install/setup.bash"
elif [[ -f "$HOME/ros2_ws/install/setup.bash" ]]; then
  # Compatibility fallback for the old standalone workspace layout.
  source "$HOME/ros2_ws/install/setup.bash"
else
  echo "ERROR: no ROS 2 workspace install/setup.bash found; build $WULIUSAI_ROS_WS first." >&2
  return 1
fi
# JetPack's apt OpenCV is built against NumPy 1.x. A user-installed NumPy 2.x
# shadows it by default and makes `import cv2` fail. Competition ROS processes
# use the known-compatible system stack without modifying user Python packages.
export PYTHONNOUSERSITE=1
