"""Record, independently analyze and replay healthy and canceled task captures."""
import argparse
from contextlib import closing
import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import time
import uuid

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.action import ActionClient
from rclpy.qos import ReliabilityPolicy
from rclpy.serialization import deserialize_message
from rosbag2_interfaces.srv import IsPaused
from reliability_interfaces.action import Reach
from reliability_interfaces.msg import TaskEvent
from reliability_interfaces.srv import Health, Reset

from .bag_analysis import TOPICS, ERROR_TOLERANCE, analyze_bag
from .replay import validate_domains

TARGETS = [[.5945, .03, .5945], [.50, -.08, .55], [.55, .10, .65]]


def stop_process(process):
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            raise RuntimeError('Process required forced termination')


class LiveClient:
    def __init__(self):
        self.node = rclpy.create_node('recording_workflow', namespace='testbench')
        self.health_client = self.node.create_client(Health, 'health')
        self.reset_client = self.node.create_client(Reset, 'reset')
        self.action = ActionClient(self.node, Reach, 'reach')

    def wait(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=.02)
            if predicate():
                return
        raise RuntimeError('Bounded recording workflow wait expired')

    def result(self, future):
        self.wait(future.done)
        return future.result()

    def health(self):
        return self.result(self.health_client.call_async(Health.Request()))

    def ready(self):
        self.wait(lambda: self.health_client.service_is_ready() and
                  self.reset_client.service_is_ready() and self.action.server_is_ready())
        deadline = time.monotonic() + 10
        while not self.health().ready:
            if time.monotonic() > deadline:
                raise RuntimeError('Live testbench not ready')


def persisted_terminal(bag, goal_id):
    """SQLite no-cache persistence barrier; final analysis always uses rosbag2_py."""
    files = list(Path(bag).glob('*.db3'))
    if not files:
        return False
    try:
        with closing(sqlite3.connect(f'file:{files[0]}?mode=ro', uri=True, timeout=.1)) as connection:
            row = connection.execute('SELECT messages.data FROM messages JOIN topics '
                'ON messages.topic_id=topics.id WHERE topics.name=? ORDER BY messages.id DESC LIMIT 1',
                ('/testbench/task_events',)).fetchone()
        if not row:
            return False
        event = deserialize_message(row[0], TaskEvent)
        return event.goal_id == goal_id and event.event == 'COMPLETED'
    except sqlite3.OperationalError:
        return False


def capture_run(client, bag, scenario, reports):
    if scenario not in ('healthy', 'cancellation'):
        raise ValueError('Unknown capture scenario: ' + scenario)
    bag, reports = Path(bag).resolve(), Path(reports).resolve()
    if bag.exists():
        raise ValueError('Refusing to overwrite an existing bag: ' + str(bag))
    bag.parent.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    client.ready()
    recorder_name = 'testbench_recorder_' + uuid.uuid4().hex[:8]
    qos = str(Path(get_package_share_directory('robot_reliability_testbench')) / 'config/bag_qos.yaml')
    command = ['ros2', 'bag', 'record', '-s', 'sqlite3', '-o', str(bag),
               '--storage-preset-profile', 'resilient',
        '--node-name', recorder_name, '--disable-keyboard-controls', '--max-cache-size', '0',
        '--qos-profile-overrides-path', qos, '--topics', *TOPICS]
    with (reports / f'{scenario}.recorder.log').open('w') as log:
        recorder = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        paused = client.node.create_client(IsPaused, '/' + recorder_name + '/is_paused')
        started = time.monotonic()
        originals = []
        try:
            def subscribed():
                if recorder.poll() is not None:
                    raise RuntimeError('Recorder exited before readiness; inspect recorder log')
                return paused.service_is_ready() and all(any(
                    endpoint.node_name == recorder_name and
                    endpoint.qos_profile.reliability == ReliabilityPolicy.RELIABLE
                    for endpoint in client.node.get_subscriptions_info_by_topic(topic)) for topic in TOPICS)
            client.wait(subscribed)
            if client.result(paused.call_async(IsPaused.Request())).paused:
                raise RuntimeError('Recorder unexpectedly paused')
            recorder_ready = time.monotonic()
            for target in (TARGETS if scenario == 'healthy' else [[.45, .25, .45]]):
                reset = client.result(client.reset_client.call_async(Reset.Request()))
                if not reset.success:
                    raise RuntimeError('Reset failed: ' + reset.message)
                deadline = time.monotonic() + 5
                while True:
                    health = client.health()
                    if health.ready and health.generation == reset.generation:
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError('Post-reset state not observed')
                request = Reach.Goal()
                request.target.x, request.target.y, request.target.z = target
                feedback = []
                wall = time.monotonic()
                handle = client.result(client.action.send_goal_async(request,
                    feedback_callback=lambda event: feedback.append(event.feedback)))
                if not handle.accepted:
                    raise RuntimeError('Capture goal unexpectedly rejected')
                goal_id = bytes(handle.goal_id.uuid).hex()
                if scenario == 'cancellation':
                    client.wait(lambda: len(feedback) >= 2)
                    if not client.result(handle.cancel_goal_async()).goals_canceling:
                        raise RuntimeError('Cancellation not accepted')
                result = client.result(handle.get_result_async())
                expected_status = 4 if scenario == 'healthy' else 5
                if result.status != expected_status:
                    raise RuntimeError(f'Unexpected action status {result.status}: {result.result.message}')
                originals.append(dict(goal_id=goal_id, status=result.status, success=result.result.success,
                    target_metres=target, final_error_metres=result.result.final_error,
                    elapsed_simulation_seconds=result.result.elapsed_time,
                    client_wall_seconds=time.monotonic()-wall, feedback_messages=len(feedback)))
                # No arbitrary drain sleep: wait until the recorder has committed this terminal event.
                client.wait(lambda: persisted_terminal(bag, goal_id))
        finally:
            stop_process(recorder)
            client.node.destroy_client(paused)
    if recorder.returncode != 0:
        raise RuntimeError(f'Recorder did not exit cleanly: {recorder.returncode}')
    analysis = analyze_bag(bag)
    by_goal = {outcome['goal_id']: outcome for outcome in analysis['outcomes']}
    if set(by_goal) != {original['goal_id'] for original in originals}:
        raise RuntimeError('Recorded goal identifiers differ from original action run')
    comparisons = []
    for original in originals:
        reconstructed = by_goal[original['goal_id']]
        error_delta = abs(original['final_error_metres'] - reconstructed['final_error_metres'])
        duration_delta = abs(original['elapsed_simulation_seconds'] - reconstructed['elapsed_simulation_seconds'])
        expected_outcome = 'succeeded' if original['success'] else 'canceled'
        if (error_delta > ERROR_TOLERANCE or duration_delta > 1e-9
                or reconstructed['outcome'] != expected_outcome or not reconstructed['matching_state_snapshot']):
            raise RuntimeError('Offline reconstruction disagrees with original run or recorded state')
        comparisons.append(dict(goal_id=original['goal_id'], outcome_match=True,
                                error_delta_metres=error_delta, simulation_duration_delta_seconds=duration_delta))
    (reports / f'{scenario}.analysis.json').write_text(json.dumps(analysis, indent=2) + '\n')
    return dict(scenario=scenario, bag=str(bag), original_actions=originals, offline=analysis,
        comparisons=comparisons, recorder_ready_before_goals=True, recorder_returncode=recorder.returncode,
        terminal_persistence_barrier=True, recorder_readiness_wall_seconds=recorder_ready-started)


def launch_replay(client, capture, reports, live_domain, replay_domain):
    validate_domains(live_domain, replay_domain)
    reports = Path(reports).resolve()
    output = reports / (capture['scenario'] + '.replay.json')
    if output.exists():
        output.unlink()  # Never accept a stale successful report after launch failure.
    with output.with_suffix('.launch.log').open('w') as log:
        process = subprocess.Popen(['ros2', 'launch', 'robot_reliability_testbench', 'replay.launch.py',
            'bag:=' + capture['bag'], 'output:=' + str(output),
            f'live_domain:={live_domain}', f'replay_domain:={replay_domain}'],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        live_samples = []
        try:
            def finished():
                names = client.node.get_node_names()
                if 'replay_monitor' in names or 'rosbag2_player' in names:
                    raise RuntimeError('Replay node discovered in live domain')
                clock_count = len(client.node.get_publishers_info_by_topic('/clock'))
                if clock_count != 1:
                    raise RuntimeError('Unexpected /clock publisher count in live domain')
                live_samples.append(clock_count)
                return process.poll() is not None
            client.wait(finished, timeout=max(25., capture['offline']['bag_receive_duration_seconds']*2+15))
        finally:
            stop_process(process)
    if process.returncode != 0 or not output.is_file():
        raise RuntimeError('Replay launch failed; inspect ' + str(output.with_suffix('.launch.log')))
    replay = json.loads(output.read_text())
    if not replay.get('success'):
        raise RuntimeError('Replay failed: ' + replay.get('error', 'unknown error'))
    replay['live_domain_isolation_check'] = dict(graph_samples=len(live_samples),
        clock_publisher_count=1, replay_nodes_discovered=False, live_health_after=client.health().healthy)
    if not replay['live_domain_isolation_check']['live_health_after']:
        raise RuntimeError('Live testbench not healthy after isolated replay')
    return replay


def run_verification(client, bag_root, reports, live_domain, replay_domain):
    validate_domains(live_domain, replay_domain)
    if int(os.environ.get('ROS_DOMAIN_ID', '0')) != live_domain:
        raise ValueError('Workflow ROS_DOMAIN_ID must equal the specified live domain')
    result = dict(milestone='C', executed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        rosbag2_py=importlib.metadata.version('rosbag2-py'), live_domain=live_domain,
        replay_domain=replay_domain, captures=[], fault_injection=False)
    for scenario in ['healthy', 'cancellation']:
        capture = capture_run(client, Path(bag_root) / scenario, scenario, reports)
        capture['replay'] = launch_replay(client, capture, reports, live_domain, replay_domain)
        result['captures'].append(capture)
    result['success'] = True
    result['limitations'] = ['Local host, SQLite3, 50 Hz, short runs; no endurance/cross-host/load validation',
        'Replay verifies per-topic counts/content/order and task-event order, not identical wall timing',
        'No fault injection or frozen/missing-state monitoring results are claimed']
    suite_file = Path(reports, 'milestone_c.tests.json')
    if suite_file.is_file():
        result['suite'] = json.loads(suite_file.read_text())
    Path(reports, 'milestone_c.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bag-root', default='bags/' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
                        + '_' + uuid.uuid4().hex[:8])
    parser.add_argument('--reports', default='reports')
    parser.add_argument('--replay-domain', type=int, default=88)
    args = parser.parse_args()
    live_domain = int(os.environ.get('ROS_DOMAIN_ID', '0'))
    validate_domains(live_domain, args.replay_domain)
    reports = Path(args.reports).resolve()
    reports.mkdir(parents=True, exist_ok=True)
    with (reports / 'milestone_c.live.launch.log').open('w') as log:
        launch = subprocess.Popen(['ros2', 'launch', 'robot_reliability_testbench', 'normal.launch.py'],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        rclpy.init()
        client = LiveClient()
        try:
            result = run_verification(client, args.bag_root, reports, live_domain, args.replay_domain)
            print(json.dumps(dict(success=result['success'],
                                 bags=[capture['bag'] for capture in result['captures']]), indent=2))
        finally:
            client.node.destroy_node()
            rclpy.shutdown()
            stop_process(launch)


if __name__ == '__main__':
    main()
