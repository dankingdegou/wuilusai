#!/usr/bin/env bash
# Source this file before running competition ROS 2 commands on the Jetson.
set -e

source /opt/ros/humble/setup.bash
source "$HOME/ros2_ws/install/setup.bash"
export WULIUSAI_REPO="${WULIUSAI_REPO:-$HOME/wuilusai}"
