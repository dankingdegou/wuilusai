#!/usr/bin/env bash
# Source this file before running competition ROS 2 commands on the Jetson.
set -e

source /opt/ros/humble/setup.bash
source "$HOME/ros2_ws/install/setup.bash"
export WULIUSAI_REPO="${WULIUSAI_REPO:-$HOME/wuilusai}"
# JetPack's apt OpenCV is built against NumPy 1.x. A user-installed NumPy 2.x
# shadows it by default and makes `import cv2` fail. Competition ROS processes
# use the known-compatible system stack without modifying user Python packages.
export PYTHONNOUSERSITE=1
