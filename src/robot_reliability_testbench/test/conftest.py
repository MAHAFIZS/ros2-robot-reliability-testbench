"""Run real installed launch processes; preserve logs and measured action outcomes."""
import datetime
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import time

import mujoco
import pytest
import rclpy
from rclpy.action import ActionClient
from rcl_interfaces.msg import Parameter as ParameterMessage, ParameterValue
from rcl_interfaces.srv import SetParameters

OUTCOMES = []
TESTS = []
REPORTS = Path(os.environ.get('TESTBENCH_REPORT_DIR', Path(__file__).resolve().parents[3] / 'reports'))


class RosClient:
    def __init__(self):
        global Reach, Health, Reset
        from reliability_interfaces.action import Reach
        from reliability_interfaces.srv import Health, Reset
        self.node = rclpy.create_node('milestone_b_tests', namespace='testbench')
        self.targets = {}
        self.health_client = self.node.create_client(Health, 'health')
        self.reset_client = self.node.create_client(Reset, 'reset')
        self.parameters = self.node.create_client(SetParameters, 'task_server/set_parameters')
        self.action = ActionClient(self.node, Reach, 'reach')

    def wait(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=.02)
            if predicate():
                return
        raise AssertionError('Bounded ROS wait expired')

    def result(self, future, timeout=8):
        self.wait(future.done, timeout)
        return future.result()

    def health(self):
        return self.result(self.health_client.call_async(Health.Request()))

    def ready(self):
        self.wait(lambda: self.health_client.service_is_ready()
                  and self.reset_client.service_is_ready()
                  and self.parameters.service_is_ready()
                  and self.action.server_is_ready(), 15)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.health().ready:
                return
        raise AssertionError('Simulator did not become ready')

    def reset(self):
        response = self.result(self.reset_client.call_async(Reset.Request()))
        assert response.success, response.message
        self.ready()
        return response

    def parameter(self, name, value):
        request = SetParameters.Request(parameters=[ParameterMessage(name=name,
            value=ParameterValue(type=3, double_value=value))])
        return self.result(self.parameters.call_async(request)).results[0]

    def send(self, target):
        request = Reach.Goal()
        request.target.x, request.target.y, request.target.z = target
        feedback = []
        start = time.monotonic()
        handle = self.result(self.action.send_goal_async(request,
                             feedback_callback=lambda msg: feedback.append(msg.feedback)))
        self.targets[bytes(handle.goal_id.uuid)] = list(target)
        return handle, feedback, start

    def outcome(self, case, sent):
        handle, feedback, start = sent
        assert handle.accepted
        response = self.result(handle.get_result_async())
        result = response.result
        OUTCOMES.append(dict(case=case, status=response.status, success=result.success,
            target_metres=self.targets[bytes(handle.goal_id.uuid)],
            final_error_metres=result.final_error, elapsed_simulation_seconds=result.elapsed_time,
            elapsed_wall_seconds=time.monotonic() - start, feedback_messages=len(feedback),
            message=result.message))
        return response, feedback


@pytest.fixture(scope='session')
def ros():
    REPORTS.mkdir(exist_ok=True)
    with open(REPORTS / 'milestone_b.regression.launch.log', 'w') as log:
        process = subprocess.Popen(['ros2', 'launch', 'robot_reliability_testbench',
                                    'normal.launch.py'], stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        rclpy.init()
        client = RosClient()
        try:
            client.ready()
            yield client
        finally:
            client.node.destroy_node()
            rclpy.shutdown()
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


@pytest.fixture
def clean_ros(ros):
    ros.reset()
    assert ros.parameter('target_tolerance', .005).successful
    assert ros.parameter('task_timeout', 5.).successful
    return ros


def pytest_runtest_logreport(report):
    if report.when == 'call' or (report.when == 'setup' and report.failed):
        TESTS.append(dict(test=report.nodeid, outcome=report.outcome,
                          wall_seconds=report.duration))


def pytest_sessionfinish(session, exitstatus):
    if not TESTS:
        return
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / 'milestone_b.regression.json').write_text(json.dumps(dict(
        milestone='B', executed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        pytest_exit_status=int(exitstatus), tests=[t for t in TESTS if 'test_ros.py' in t['test'] or 'test_simulation.py' in t['test']], actions=OUTCOMES,
        environment=dict(python=platform.python_version(), mujoco=mujoco.__version__,
                         platform=platform.platform(), ros_distro=os.environ.get('ROS_DISTRO')),
        timing='Action elapsed_time is MuJoCo duration; wall time includes ROS request/result transport.',
        limitations=['Single local host, headless software simulation only',
                     'No rosbag, fault injection, Docker, CI or endurance validation']), indent=2) + '\n')
    if any('test_bags' in test['test'] for test in TESTS):
        previous_tests = [t for t in TESTS if any(name in t['test'] for name in
                          ['test_bags.py', 'test_ros.py', 'test_simulation.py'])]
        suite = dict(executed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     pytest_exit_status=int(exitstatus), tests=previous_tests,
                     passed=sum(t['outcome'] == 'passed' for t in previous_tests),
                     failed=sum(t['outcome'] == 'failed' for t in previous_tests))
        (REPORTS / 'milestone_c.tests.json').write_text(json.dumps(suite, indent=2) + '\n')
        report = REPORTS / 'milestone_c.json'
        if report.exists():
            data = json.loads(report.read_text())
            data['suite'] = suite
            report.write_text(json.dumps(data, indent=2) + '\n')
    if any('test_fault' in test['test'] or 'test_monitor' in test['test'] for test in TESTS):
        suite = dict(executed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     pytest_exit_status=int(exitstatus), tests=TESTS,
                     passed=sum(t['outcome'] == 'passed' for t in TESTS),
                     failed=sum(t['outcome'] == 'failed' for t in TESTS))
        (REPORTS / 'milestone_d.tests.json').write_text(json.dumps(suite, indent=2) + '\n')
        report = REPORTS / 'milestone_d.json'
        if report.exists():
            data = json.loads(report.read_text())
            data['suite'] = suite
            report.write_text(json.dumps(data, indent=2) + '\n')
