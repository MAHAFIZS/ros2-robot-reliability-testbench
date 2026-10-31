"""Starts only the observer/player supervisor, with an isolated child domain."""
import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, RegisterEventHandler, EmitEvent
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def start(context):
    live = int(LaunchConfiguration('live_domain').perform(context))
    replay = int(LaunchConfiguration('replay_domain').perform(context))
    if not 0 <= live <= 232 or not 0 <= replay <= 232 or live == replay:
        raise ValueError('Replay domain must be valid and different from the live domain')
    monitor = Node(package='robot_reliability_testbench', executable='replay_session',
        name='replay_monitor', namespace='replay', output='screen',
        additional_env={'ROS_DOMAIN_ID': str(replay), 'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST'},
        arguments=['--bag', LaunchConfiguration('bag'), '--output', LaunchConfiguration('output'),
                   '--live-domain', str(live), '--replay-domain', str(replay)])
    return [RegisterEventHandler(OnProcessExit(target_action=monitor,
                on_exit=[EmitEvent(event=Shutdown(reason='Observation-only replay finished'))])), monitor]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('bag'), DeclareLaunchArgument('output', default_value='reports/replay.json'),
        DeclareLaunchArgument('live_domain', default_value=os.environ.get('ROS_DOMAIN_ID', '0')),
        DeclareLaunchArgument('replay_domain', default_value='88'), OpaqueFunction(function=start)])
