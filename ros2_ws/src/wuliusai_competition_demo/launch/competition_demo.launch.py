from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("config", description="Competition demo YAML configuration"),
        Node(
            package="wuliusai_competition_demo",
            executable="competition_demo",
            name="competition_demo",
            output="screen",
            parameters=[{"config_file": LaunchConfiguration("config")}],
        ),
    ])
