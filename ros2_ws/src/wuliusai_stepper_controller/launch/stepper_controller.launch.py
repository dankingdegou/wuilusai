from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    config = os.path.join(get_package_share_directory("wuliusai_stepper_controller"), "config", "stepper_controller.yaml")
    return LaunchDescription([Node(
        package="wuliusai_stepper_controller",
        executable="stepper_controller",
        name="stepper_controller",
        output="screen",
        parameters=[config],
    )])
