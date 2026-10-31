"""Launch the installed system and measure three reaches through ROS clients."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

import rclpy
from rclpy.action import ActionClient
from reliability_interfaces.action import Reach
from reliability_interfaces.srv import Health, Reset


def main():
    reports = Path(os.environ.get('TESTBENCH_REPORT_DIR', 'reports'))
    reports.mkdir(exist_ok=True)
    with (reports / 'milestone_b.demo.launch.log').open('w') as log:
        process = subprocess.Popen(['ros2', 'launch', 'robot_reliability_testbench',
                                    'normal.launch.py'], stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        rclpy.init()
        node = rclpy.create_node('milestone_b_demo', namespace='testbench')
        health = node.create_client(Health, 'health')
        reset = node.create_client(Reset, 'reset')
        action = ActionClient(node, Reach, 'reach')
        def wait(predicate, timeout=10):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=.02)
                if predicate():
                    return
                if process.poll() is not None:
                    raise RuntimeError('Launch exited; inspect demo launch log')
            raise RuntimeError('Demo readiness/result deadline exceeded')
        def result(future):
            wait(future.done)
            return future.result()
        started = time.monotonic()
        measurements = []
        try:
            wait(lambda: health.service_is_ready() and reset.service_is_ready()
                 and action.server_is_ready())
            readiness_deadline = time.monotonic() + 10
            while not result(health.call_async(Health.Request())).ready:
                if time.monotonic() > readiness_deadline:
                    raise RuntimeError('Simulator not ready')
            for target in [[.5945, .03, .5945], [.50, -.08, .55], [.55, .10, .65]]:
                restored = result(reset.call_async(Reset.Request()))
                assert restored.success, restored.message
                # Wait for the acknowledged generation to appear on the task server.
                deadline = time.monotonic() + 5
                while True:
                    status = result(health.call_async(Health.Request()))
                    if status.ready and status.generation == restored.generation:
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError('Post-reset observation deadline exceeded')
                request = Reach.Goal()
                request.target.x, request.target.y, request.target.z = target
                feedback = []
                wall_start = time.monotonic()
                handle = result(action.send_goal_async(request,
                    feedback_callback=lambda msg: feedback.append(msg.feedback.distance)))
                assert handle.accepted, 'Demo target rejected'
                response = result(handle.get_result_async())
                measured = dict(target_metres=target, status=response.status,
                    success=response.result.success, final_error_metres=response.result.final_error,
                    elapsed_simulation_seconds=response.result.elapsed_time,
                    elapsed_wall_seconds=time.monotonic() - wall_start,
                    feedback_messages=len(feedback))
                measurements.append(measured)
                assert response.result.success and response.result.final_error <= .005, measured
            assert result(health.call_async(Health.Request())).healthy
            demonstration = dict(success=True, reaches=measurements,
                                 total_wall_seconds=time.monotonic() - started)
            (reports / 'milestone_b.demo.json').write_text(json.dumps(demonstration, indent=2) + '\n')
            report_file = reports / 'milestone_b.json'
            if report_file.exists():
                report = json.loads(report_file.read_text())
                report['launch_demonstration'] = demonstration
                report_file.write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(demonstration, indent=2))
        finally:
            node.destroy_node()
            rclpy.shutdown()
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


if __name__ == '__main__':
    main()
