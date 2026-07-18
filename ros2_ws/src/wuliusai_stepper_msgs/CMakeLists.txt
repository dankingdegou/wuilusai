cmake_minimum_required(VERSION 3.8)
project(wuliusai_stepper_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "action/MoveAxis.action"
  "action/MoveGantry.action"
  "action/ExecuteScoop.action"
  "msg/StepperState.msg"
  "srv/SetAxisZero.srv"
  "srv/SetGantryZero.srv"
  "srv/StopAxis.srv"
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
