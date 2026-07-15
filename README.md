# Wuliusai competition control

ROS 2 and STM32 source for the logistics competition robot.

## Contents

- `firmware/bjdj`: STM32F103VET6 dual-stepper firmware for the gantry rails.
- `ros2_ws/src/wuliusai_stepper_msgs`: ROS 2 interfaces for the gantry.
- `ros2_ws/src/wuliusai_stepper_controller`: ROS 2 serial bridge and gantry Action node.
- `ros2_ws/src/ros_robot_controller-ros2`: ROS 2 driver for the separate bus-servo STM32 controller.
- `scripts`: safe communication, single-axis, gantry-sync, and HX-35HM test tools.
- `docs`: Chinese deployment and architecture documentation.

## Jetson Orin NX deployment

The Jetson runs Ubuntu 22.04 / ROS 2 Humble. Clone this repository into a local directory, then copy or symlink the packages under `ros2_ws/src` into the Jetson ROS workspace and build them natively:

```bash
source /opt/ros/humble/setup.bash
cd ~/ros2_ws
colcon build --symlink-install --packages-select \
  wuliusai_stepper_msgs wuliusai_stepper_controller
source install/setup.bash
```

The STM32 firmware must be compiled and flashed separately. Do not copy an x86 ROS `build/` or `install/` directory to the Jetson.

## Safety

The gantry's two rails are mechanically coupled. Use `/stepper_controller/move_gantry` for normal operation; do not issue independent axis commands to move the two rails. Without physical home/limit switches or encoders, absolute motion requires manual zeroing after every power-up or fault.
