"""Observation-only replay supervisor and subscriber, in a separate ROS domain."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rosbag2_interfaces.srv import Resume
from rosidl_runtime_py.utilities import get_message

from .bag_analysis import TOPICS, TopicDigest, analyze_bag


def validate_domains(live_domain, replay_domain):
    if not 0 <= live_domain <= 232 or not 0 <= replay_domain <= 232:
        raise ValueError('Domain IDs must be within [0, 232]')
    if live_domain == replay_domain:
        raise ValueError('Replay domain must differ from the live domain')


def replay_bag(bag, output, live_domain, replay_domain):
    validate_domains(live_domain, replay_domain)
    if int(os.environ.get('ROS_DOMAIN_ID', '0')) != replay_domain:
        raise ValueError('Replay process ROS_DOMAIN_ID does not match its isolated domain')
    expected = analyze_bag(bag)
    rclpy.init()
    node = rclpy.create_node('replay_monitor', namespace='replay')
    digests = {topic: TopicDigest() for topic in TOPICS}
    event_order = []
    process = None
    started = time.monotonic()
    def wait(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.02)
            if predicate():
                return
            if process is not None and process.poll() not in (None, 0):
                raise RuntimeError('Bag player failed; inspect playback log')
        raise RuntimeError('Bounded replay readiness/playback wait expired')
    try:
        def receive(topic, message):
            digests[topic].add(message)
            if topic == '/testbench/task_events':
                event_order.append([message.session_id, message.sequence, message.goal_id, message.event])
        subscriptions = [node.create_subscription(get_message(type_name), topic,
                            lambda message, topic=topic: receive(topic, message), QoSProfile(depth=1000))
                         for topic, type_name in TOPICS.items()]
        # A native service roundtrip below provides the player discovery barrier.
        # Refuse any competing observation publisher, even in the replay domain.
        for topic in TOPICS:
            if node.get_publishers_info_by_topic(topic):
                raise RuntimeError('Replay domain already has an observation publisher: ' + topic)
        qos = str(Path(get_package_share_directory('robot_reliability_testbench')) / 'config/bag_qos.yaml')
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.with_suffix('.player.log').open('w') as log:
            process = subprocess.Popen(['ros2', 'bag', 'play', str(bag), '--start-paused',
                '--disable-keyboard-controls', '--wait-for-all-acked', '3000',
                '--qos-profile-overrides-path', qos, '--topics', *TOPICS],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            resume = node.create_client(Resume, '/rosbag2_player/resume')
            def discovered():
                return resume.service_is_ready() and all(
                    any(p.node_name == 'rosbag2_player' and p.qos_profile.reliability == ReliabilityPolicy.RELIABLE
                        for p in node.get_publishers_info_by_topic(topic)) for topic in TOPICS)
            wait(discovered)
            publisher_nodes = {}
            for topic in TOPICS:
                publishers = node.get_publishers_info_by_topic(topic)
                if len(publishers) != 1 or publishers[0].node_name != 'rosbag2_player':
                    raise RuntimeError('Competing replay publisher: ' + topic)
                publisher_nodes[topic] = publishers[0].node_name
            names = node.get_node_names()
            if 'panda_simulator' in names or 'task_server' in names:
                raise RuntimeError('Live testbench detected in replay domain')
            forbidden_services = [name for name, _ in node.get_service_names_and_types()
                                  if name.startswith('/testbench/')]
            if forbidden_services:
                raise RuntimeError('Live command/service graph detected in replay domain')
            unexpected_topics = [name for name, _ in node.get_topic_names_and_types()
                                 if name.startswith('/testbench/') and name not in TOPICS]
            if unexpected_topics:
                raise RuntimeError('Unexpected testbench topic in replay graph: ' + str(unexpected_topics))
            ready = time.monotonic()
            future = resume.call_async(Resume.Request())
            wait(future.done)
            future.result()
            wait(lambda: process.poll() is not None and all(
                digests[t].count >= expected['topics'][t]['count'] for t in TOPICS),
                timeout=max(15., expected['bag_receive_duration_seconds'] * 2 + 5))
            actual = {topic: digest.summary() for topic, digest in digests.items()}
            for topic in TOPICS:
                if actual[topic] != {k: expected['topics'][topic][k] for k in ['count', 'sha256']}:
                    raise RuntimeError('Replay count/content/order mismatch on ' + topic)
            expected_order = [[e['session_id'], e['sequence'], e['goal_id'], e['event']]
                              for e in expected['task_events']]
            if event_order != expected_order:
                raise RuntimeError('Replay task-event order mismatch')
            result = dict(success=True, live_domain=live_domain, replay_domain=replay_domain,
                topics=actual, task_event_order=event_order, publisher_nodes=publisher_nodes,
                clock_policy='Recorded /clock only; no synthetic player clock',
                command_services_in_replay=forbidden_services, subscribers_ready_before_resume=True,
                unexpected_testbench_topics=unexpected_topics, excluded_bag_topics=expected['ignored_topics'],
                readiness_wall_seconds=ready-started, playback_wall_seconds=time.monotonic()-ready,
                timing_comparison='Wall timing is not required to match capture; per-topic contents and event order are exact')
            output.write_text(json.dumps(result, indent=2) + '\n')
            return result
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        node.destroy_node()
        rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bag', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--live-domain', required=True, type=int)
    parser.add_argument('--replay-domain', required=True, type=int)
    args = parser.parse_args(rclpy.utilities.remove_ros_args()[1:])
    try:
        result = replay_bag(args.bag, args.output, args.live_domain, args.replay_domain)
    except Exception as exc:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(dict(success=False, error=str(exc)), indent=2) + '\n')
        raise
    print(json.dumps(dict(success=result['success'], topics=result['topics']), indent=2))


if __name__ == '__main__':
    main()
