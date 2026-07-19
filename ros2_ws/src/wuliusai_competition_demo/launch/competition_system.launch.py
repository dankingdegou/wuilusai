import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    controller_share = get_package_share_directory("wuliusai_stepper_controller")
    x_config = os.path.join(controller_share, "config", "stepper_controller.yaml")
    yz_config = os.path.join(controller_share, "config", "yz_controller.yaml")
    return LaunchDescription([
        DeclareLaunchArgument("config", description="Calibrated competition demo YAML configuration"),
        Node(
            package="wuliusai_stepper_controller",
            executable="stepper_controller",
            name="stepper_controller",
            output="screen",
            parameters=[x_config],
        ),
        Node(
            package="wuliusai_stepper_controller",
            executable="stepper_controller",
            name="yz_controller",
            output="screen",
            parameters=[yz_config],
        ),
        Node(
            package="wuliusai_competition_demo",
            executable="competition_demo",
            name="competition_demo",
            output="screen",
            parameters=[{"config_file": LaunchConfiguration("config")}],
        ),
    ])
