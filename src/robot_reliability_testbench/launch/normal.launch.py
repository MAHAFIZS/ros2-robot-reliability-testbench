from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    config = str(Path(get_package_share_directory('robot_reliability_testbench')) / 'config/normal.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=config),
        Node(package='robot_reliability_testbench', executable='simulator',
             namespace='testbench', name='panda_simulator', output='screen',
             parameters=[LaunchConfiguration('params_file')]),
        Node(package='robot_reliability_testbench', executable='task_server',
             namespace='testbench', name='task_server', output='screen',
             parameters=[LaunchConfiguration('params_file')]),
        Node(package='robot_reliability_testbench', executable='fault_boundary',
             namespace='testbench', name='fault_boundary', output='screen'),
        Node(package='robot_reliability_testbench', executable='health_monitor',
             namespace='testbench', name='health_monitor', output='screen',
             parameters=[LaunchConfiguration('params_file')]),
    ])
