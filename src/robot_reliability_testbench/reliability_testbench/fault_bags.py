"""D capture analysis and fresh-monitor replay, preserving C's five-topic contract."""
import argparse
import json
import os
from pathlib import Path
import signal
import sqlite3
from contextlib import closing
import subprocess
import time

from ament_index_python.packages import get_package_share_directory
import rosbag2_py
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile
from rclpy.serialization import deserialize_message
from rosbag2_interfaces.srv import IsPaused, Resume
from rosidl_runtime_py.convert import message_to_ordereddict
from rosidl_runtime_py.utilities import get_message

from .bag_analysis import TOPICS, TopicDigest, analyze_bag, timing, message_stamp
from .bag_workflow import stop_process
from .health_monitor import HealthMonitor
from .replay import validate_domains

D_TOPICS = dict(TOPICS, **{
    '/testbench/observed/state': 'reliability_interfaces/msg/ObservedState',
    '/testbench/observed/joint_states': 'sensor_msgs/msg/JointState',
    '/testbench/observed/ee_pose': 'geometry_msgs/msg/PoseStamped',
    '/testbench/task_intent': 'reliability_interfaces/msg/TaskIntent',
    '/testbench/fault_events': 'reliability_interfaces/msg/FaultEvent',
    '/testbench/command_events': 'reliability_interfaces/msg/CommandEvent',
    '/testbench/diagnostics': 'reliability_interfaces/msg/DiagnosticEvent',
})
MONITOR_INPUTS = ['/testbench/observed/state', '/testbench/task_intent', '/clock']


def diagnostic_signature(events):
    # Gaps are observation-driven. Lifecycle includes a steady watchdog and a
    # separate intent writer: cross-channel interleaving is not a total order.
    return dict(lifecycle=[[e['reason_code'], e['active'], e['recovered_reason'], e['goal_id']]
                           for e in events if e['reason_code'] != 'OBSERVATION_GAP'],
                gaps=[[e['reason_code'], e['generation'], e['observation_sequence'], e['missing_count']]
                      for e in events if e['reason_code'] == 'OBSERVATION_GAP'])


def analyze_fault_bag(bag):
    base = analyze_bag(bag)
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(bag)), rosbag2_py.ConverterOptions('', ''))
    try:
        available = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
        for topic, type_name in D_TOPICS.items():
            if available.get(topic) != type_name:
                raise ValueError('Missing or wrong milestone D topic: ' + topic)
        types = {topic: get_message(type_name) for topic, type_name in D_TOPICS.items()}
        digests = {topic: TopicDigest() for topic in D_TOPICS}
        receive = {topic: [] for topic in D_TOPICS}
        stamps = {topic: [] for topic in D_TOPICS}
        events = dict(diagnostics=[], faults=[], commands=[], intent=[])
        categories = {'/testbench/diagnostics': 'diagnostics', '/testbench/fault_events': 'faults',
                      '/testbench/command_events': 'commands', '/testbench/task_intent': 'intent'}
        while reader.has_next():
            topic, data, received = reader.read_next()
            if topic not in D_TOPICS:
                continue
            message = deserialize_message(data, types[topic])
            digests[topic].add(message)
            receive[topic].append(received)
            stamps[topic].append(message_stamp(message))
            if topic in categories:
                event = message_to_ordereddict(message)
                event['bag_receive_ns'] = received
                event['message_stamp_ns'] = message_stamp(message)
                events[categories[topic]].append(event)
        for topic in D_TOPICS:
            if not receive[topic] and topic != '/testbench/diagnostics':
                raise ValueError('Empty milestone D required topic: ' + topic)
        command_delays = [dict(goal_id=e['goal_id'], sequence=e['sequence'],
                              actual_delay_simulation_seconds=e['applied_simulation_time']-e['enqueued_simulation_time'],
                              configured_delay_simulation_seconds=e['due_simulation_time']-e['enqueued_simulation_time'])
                          for e in events['commands'] if e['operation'] == 0 and e['event'] == 'APPLIED']
        fault_latency = []
        for event in events['diagnostics']:
            relevant = [f for f in events['faults'] if f['bag_receive_ns'] <= event['bag_receive_ns']]
            if relevant:
                prior = relevant[-1]
                fault_latency.append(dict(reason_code=event['reason_code'], fault_revision=prior['revision'],
                    receive_latency_seconds=(event['bag_receive_ns']-prior['bag_receive_ns'])/1e9,
                    simulation_stamp_delta_seconds=((event['message_stamp_ns']-prior['message_stamp_ns'])/1e9
                        if event['generation'] == prior['generation'] else None)))
        return dict(bag=str(bag), tasks=base['outcomes'], bag_receive_duration_seconds=base['bag_receive_duration_seconds'],
            topics={topic: dict(type=D_TOPICS[topic], **digests[topic].summary(),
                bag_receive=timing(receive[topic]) if receive[topic] else None,
                message_stamp=timing(stamps[topic]) if stamps[topic] else None) for topic in D_TOPICS},
            **events, command_delays=command_delays, fault_to_diagnostic_timing=fault_latency,
            diagnostic_signature=diagnostic_signature(events['diagnostics']),
            timing_limitations='Receive latency includes independent DDS/recorder scheduling; simulation stamps '
                'can reset. Fault-to-diagnostic association is temporal evidence, not monitor root-cause inference.')
    finally:
        reader.close()


class FaultRecorder:
    def __init__(self, client, bag, reports):
        self.client, self.bag, self.reports = client, Path(bag).resolve(), Path(reports).resolve()

    def __enter__(self):
        if self.bag.exists():
            raise ValueError('Refusing to overwrite bag: ' + str(self.bag))
        self.bag.parent.mkdir(parents=True, exist_ok=True)
        self.reports.mkdir(parents=True, exist_ok=True)
        qos = self.reports / 'milestone_d.bag_qos.yaml'
        qos.write_text(''.join(f'{topic}:\n  reliability: reliable\n  durability: volatile\n'
                              '  history: keep_last\n  depth: 1000\n' for topic in D_TOPICS))
        self.log = (self.reports / 'milestone_d.recorder.log').open('w')
        self.process = subprocess.Popen(['ros2', 'bag', 'record', '-s', 'sqlite3', '-o', str(self.bag),
            '--storage-preset-profile', 'resilient',
            '--node-name', 'fault_recorder', '--disable-keyboard-controls', '--max-cache-size', '0',
            '--qos-profile-overrides-path', str(qos), '--topics', *D_TOPICS],
            stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        self.paused = self.client.node.create_client(IsPaused, '/fault_recorder/is_paused')
        try:
            self.client.wait(lambda: self.paused.service_is_ready() and all(any(
                endpoint.node_name == 'fault_recorder' for endpoint in
                self.client.node.get_subscriptions_info_by_topic(topic)) for topic in D_TOPICS))
            if self.client.result(self.paused.call_async(IsPaused.Request())).paused:
                raise RuntimeError('Fault recorder is paused')
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def drain(self, session):
        # Require committed observation, fault and diagnostic tails, not a guessed sleep.
        snapshots = {}
        for key, topic in [('observed', '/testbench/observed/state'), ('fault', '/testbench/fault_events'),
                           ('diagnostic', '/testbench/diagnostics')]:
            if session.messages[key]:
                message = session.messages[key][-1][1]
                field = 'revision' if key == 'fault' else 'sequence'
                snapshots[topic] = (field, getattr(message, field))
        def committed():
            files = list(self.bag.glob('*.db3'))
            if not files:
                return False
            try:
                with closing(sqlite3.connect(f'file:{files[0]}?mode=ro', uri=True, timeout=.1)) as connection:
                    for topic, (field, minimum) in snapshots.items():
                        row = connection.execute('SELECT messages.data FROM messages JOIN topics ON '
                            'messages.topic_id=topics.id WHERE topics.name=? ORDER BY messages.id DESC LIMIT 1',
                            (topic,)).fetchone()
                        if row is None or getattr(deserialize_message(row[0], get_message(D_TOPICS[topic])), field) < minimum:
                            return False
                return True
            except sqlite3.OperationalError:
                return False
        self.client.wait(committed)

    def __exit__(self, *args):
        stop_process(self.process)
        self.client.node.destroy_client(self.paused)
        self.log.close()
        if self.process.returncode != 0:
            raise RuntimeError('Fault recorder did not close cleanly')


def replay_fault_bag(bag, output, live_domain, replay_domain):
    validate_domains(live_domain, replay_domain)
    if int(os.environ.get('ROS_DOMAIN_ID', '0')) != replay_domain:
        raise ValueError('Fresh monitor must run in the isolated replay domain')
    expected = analyze_fault_bag(bag)
    first_observation = expected['topics']['/testbench/observed/state']['bag_receive']['first_ns']
    if any(event['bag_receive_ns'] < first_observation for event in expected['diagnostics']):
        raise ValueError('Capture lacks an observation baseline before recorded diagnostics; cannot verify replay')
    rclpy.init(args=[])
    observer = rclpy.create_node('fault_replay_observer', namespace='replay')
    monitor = HealthMonitor(replay=True)
    executor = SingleThreadedExecutor()
    executor.add_node(observer)
    executor.add_node(monitor)
    digests = {topic: TopicDigest() for topic in MONITOR_INPUTS}
    new_diagnostics = []
    subscriptions = []
    for topic in MONITOR_INPUTS:
        subscriptions.append(observer.create_subscription(get_message(D_TOPICS[topic]), topic,
            lambda message, topic=topic: digests[topic].add(message), QoSProfile(depth=1000)))
    subscriptions.append(observer.create_subscription(get_message(D_TOPICS['/testbench/diagnostics']),
        '/replay/diagnostics', lambda message: new_diagnostics.append(message_to_ordereddict(message)), QoSProfile(depth=1000)))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    process = None
    def wait(predicate, timeout=20):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            executor.spin_once(timeout_sec=.005)
            if predicate():
                return
            if process is not None and process.poll() not in (None, 0):
                raise RuntimeError('Fault replay player exited abnormally')
        raise RuntimeError('Bounded fresh-monitor replay wait expired')
    try:
        qos = Path(get_package_share_directory('robot_reliability_testbench')) / 'config/bag_qos.yaml'
        with output.with_suffix('.player.log').open('w') as log:
            process = subprocess.Popen(['ros2', 'bag', 'play', str(bag), '--start-paused',
                '--disable-keyboard-controls', '--wait-for-all-acked', '3000',
                '--topics', *MONITOR_INPUTS], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            resume = observer.create_client(Resume, '/rosbag2_player/resume')
            wait(lambda: resume.service_is_ready() and all(len(observer.get_publishers_info_by_topic(topic)) == 1
                and observer.get_publishers_info_by_topic(topic)[0].node_name == 'rosbag2_player' for topic in MONITOR_INPUTS))
            if any(name in observer.get_node_names() for name in ['panda_simulator', 'task_server', 'fault_boundary']):
                raise RuntimeError('Live simulator/controller/boundary discovered in replay domain')
            forbidden = [topic for topic in D_TOPICS if topic not in MONITOR_INPUTS
                         and observer.get_publishers_info_by_topic(topic)]
            if forbidden:
                raise RuntimeError('Recorded diagnostics, raw state or fault labels published into fresh replay: ' + str(forbidden))
            monitor.core.started = time.monotonic()
            started = time.monotonic()
            future = resume.call_async(Resume.Request())
            wait(future.done)
            mapping = {'/testbench/observed/state': 'observation', '/testbench/task_intent': 'intent', '/clock': 'clock'}
            wait(lambda: all(digests[t].count == expected['topics'][t]['count'] and
                 monitor.received_counts[mapping[t]] == expected['topics'][t]['count'] for t in MONITOR_INPUTS),
                 timeout=max(20., expected['bag_receive_duration_seconds']*2+5))
            # Stop watchdog at the captured input horizon, not player teardown time.
            monitor.timer.cancel()
            wait(lambda: len(new_diagnostics) == monitor.diagnostic_count)
            process.wait(timeout=10)
            for topic, digest in digests.items():
                if digest.summary() != {key: expected['topics'][topic][key] for key in ['count', 'sha256']}:
                    raise RuntimeError('Fresh monitor input loss/content/order mismatch: ' + topic)
            signature = diagnostic_signature(new_diagnostics)
            if signature != expected['diagnostic_signature']:
                output.write_text(json.dumps(dict(success=False, recorded_diagnostics=expected['diagnostics'],
                    new_diagnostics=new_diagnostics, expected_signature=expected['diagnostic_signature'],
                    actual_signature=signature), indent=2)+'\n')
                raise RuntimeError('Fresh diagnostics disagree with bag diagnostics: ' +
                                   json.dumps(dict(expected=expected['diagnostic_signature'], actual=signature)))
            result = dict(success=True, live_domain=live_domain, replay_domain=replay_domain,
                replayed_topics=MONITOR_INPUTS, forbidden_published_topics=forbidden,
                inputs={topic: digest.summary() for topic, digest in digests.items()},
                recorded_diagnostics=expected['diagnostics'], new_diagnostics=new_diagnostics,
                new_diagnostic_topic='/replay/diagnostics', comparison=signature,
                watchdog_arming='First captured affected observation; recorder-discovery prefix is incomplete',
                playback_wall_seconds=time.monotonic()-started,
                limitation='Reason/lifecycle order and gap order compared separately; steady watchdog timing and '
                           'cross-writer interleaving need not be identical. No recorded diagnostic/fault label is an input.')
            output.write_text(json.dumps(result, indent=2)+'\n')
            return result
    finally:
        if process is not None:
            stop_process(process)
        executor.shutdown()
        monitor.destroy_node()
        observer.destroy_node()
        rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bag', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--live-domain', type=int, required=True)
    parser.add_argument('--replay-domain', type=int, required=True)
    args = parser.parse_args()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(dict(success=False, bag=args.bag, phase='starting'))+'\n')
    try:
        replay_fault_bag(args.bag, args.output, args.live_domain, args.replay_domain)
    except Exception as exc:
        failure = json.loads(Path(args.output).read_text())
        failure.update(success=False, error=str(exc))
        Path(args.output).write_text(json.dumps(failure, indent=2)+'\n')
        raise


def analysis_main():
    parser = argparse.ArgumentParser(description='Analyze D fault captures with rosbag2_py')
    parser.add_argument('bag')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = analyze_fault_bag(args.bag)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
