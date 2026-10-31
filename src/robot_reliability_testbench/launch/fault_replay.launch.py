"""Only affected observations/intent/clock feed a fresh isolated monitor."""
import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, ExecuteProcess, RegisterEventHandler, EmitEvent
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackagePrefix


def start(context):
    live = int(LaunchConfiguration('live_domain').perform(context))
    replay = int(LaunchConfiguration('replay_domain').perform(context))
    if live == replay or not 0 <= live <= 232 or not 0 <= replay <= 232:
        raise ValueError('Fresh-monitor replay requires a different valid ROS domain')
    process = ExecuteProcess(cmd=[PathJoinSubstitution([FindPackagePrefix('robot_reliability_testbench'),
        'lib', 'robot_reliability_testbench', 'fault_replay']),
        '--bag', LaunchConfiguration('bag'), '--output', LaunchConfiguration('output'),
        '--live-domain', str(live), '--replay-domain', str(replay)], output='screen',
        additional_env={'ROS_DOMAIN_ID': str(replay), 'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST'})
    return [RegisterEventHandler(OnProcessExit(target_action=process,
                on_exit=[EmitEvent(event=Shutdown(reason='Fresh-monitor replay finished'))])), process]


def generate_launch_description():
    return LaunchDescription([DeclareLaunchArgument('bag'),
        DeclareLaunchArgument('output', default_value='reports/milestone_d.replay.json'),
        DeclareLaunchArgument('live_domain', default_value=os.environ.get('ROS_DOMAIN_ID', '0')),
        DeclareLaunchArgument('replay_domain', default_value='88'), OpaqueFunction(function=start)])
