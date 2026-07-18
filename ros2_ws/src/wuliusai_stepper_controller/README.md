# Wuliusai dual-stepper ROS2 controller

Build:

```bash
cd /home/rog/ros2_ws/wuliusai/ros2_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
ros2 launch wuliusai_stepper_controller stepper_controller.launch.py
```

The board now exposes an STM32 native USB CDC virtual serial port. Identify it with `udevadm info -q property -n /dev/ttyACM0` (replace the device name). Create `/etc/udev/rules.d/99-wuliusai-stepper.rules` using its unique `ID_VENDOR_ID`, `ID_MODEL_ID` and `ID_SERIAL`, with a rule such as:

```text
SUBSYSTEM=="tty", ENV{ID_BUS}=="usb", ENV{ID_VENDOR_ID}=="0483", ENV{ID_MODEL_ID}=="5740", ENV{ID_SERIAL}=="your_firmware_usb_serial", SYMLINK+="stepper_controller", MODE="0660", GROUP="dialout"
```

Then run `sudo udevadm control --reload-rules && sudo udevadm trigger` and reconnect the adapter. Do not create a rule until the actual adapter identifiers have been read.

Before using absolute moves, manually set the mechanical zero after every board power-up:

```bash
ros2 service call /stepper_controller/set_zero wuliusai_stepper_msgs/srv/SetAxisZero "{axis: 0, position: 0.0}"
```

Example relative move in the configured physical unit:

```bash
ros2 action send_goal /stepper_controller/move_axis wuliusai_stepper_msgs/action/MoveAxis "{axis: 0, relative: true, target: 10.0, max_speed: 0.0}" --feedback
```

`max_speed: 0.0` uses the YAML default. Do not use the default calibration values on the assembled robot: set `pulses_per_unit`, direction, limits, speed and acceleration after measurement.
