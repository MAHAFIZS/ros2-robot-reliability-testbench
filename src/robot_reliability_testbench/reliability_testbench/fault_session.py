"""ROS-only measurement helper shared by regression tests and the short demo."""
import time

from rclpy.qos import QoSProfile
from reliability_interfaces.action import Reach
from reliability_interfaces.msg import (SimulationState, ObservedState, TaskIntent, FaultConfiguration,
                                        FaultEvent, CommandEvent, DiagnosticEvent)
from reliability_interfaces.srv import ConfigureFaults, MonitorStatus, Reset
from rcl_interfaces.srv import SetParameters
from rclpy.parameter import Parameter


class FaultSession:
    def __init__(self, client):
        self.client = client
        self.node = client.node
        self.config = self.node.create_client(ConfigureFaults, '/testbench/configure_faults')
        self.status_client = self.node.create_client(MonitorStatus, '/testbench/observation_health')
        self.messages = {}
        self.subscriptions = []
        for key, topic, message in [
            ('raw', '/testbench/simulation_state', SimulationState),
            ('observed', '/testbench/observed/state', ObservedState),
            ('intent', '/testbench/task_intent', TaskIntent),
            ('fault', '/testbench/fault_events', FaultEvent),
            ('command', '/testbench/command_events', CommandEvent),
            ('diagnostic', '/testbench/diagnostics', DiagnosticEvent)]:
            self.messages[key] = []
            self.subscriptions.append(self.node.create_subscription(message, topic,
                lambda message, key=key: self.messages[key].append((time.monotonic(), message)), QoSProfile(depth=1000)))

    def close(self):
        for subscription in self.subscriptions:
            self.node.destroy_subscription(subscription)
        self.node.destroy_client(self.config)
        self.node.destroy_client(self.status_client)

    def ready(self):
        self.client.ready()
        self.client.wait(lambda: self.config.service_is_ready() and self.status_client.service_is_ready()
                         and bool(self.messages['raw']) and bool(self.messages['observed']))

    def status(self):
        return self.client.result(self.status_client.call_async(MonitorStatus.Request()))

    def reset(self):
        response = self.client.result(self.client.reset_client.call_async(Reset.Request()))
        if not response.success:
            raise RuntimeError(response.message)
        self.client.wait(lambda: self.messages['observed'][-1][1].generation == response.generation)
        self.client.ready()
        return response

    def configure(self, **fields):
        configuration = FaultConfiguration(**fields)
        result = self.client.result(self.config.call_async(ConfigureFaults.Request(configuration=configuration)))
        if not result.accepted:
            raise ValueError(result.message)
        return result

    def wait_sim(self, seconds):
        start = self.messages['raw'][-1][1]
        self.client.wait(lambda: self.messages['raw'][-1][1].generation == start.generation and
                         self.messages['raw'][-1][1].simulation_time >= start.simulation_time+seconds,
                         timeout=max(5., seconds*3))

    def parameter(self, name, value):
        client = self.node.create_client(SetParameters, '/testbench/task_server/set_parameters')
        try:
            self.client.wait(client.service_is_ready)
            response = self.client.result(client.call_async(SetParameters.Request(
                parameters=[Parameter(name, value=value).to_parameter_msg()])))
            if not response.results[0].successful:
                raise ValueError(response.results[0].reason)
        finally:
            self.node.destroy_client(client)

    def send(self, target=(.45, .25, .45)):
        goal = Reach.Goal()
        goal.target.x, goal.target.y, goal.target.z = target
        feedback = []
        wall = time.monotonic()
        handle = self.client.result(self.client.action.send_goal_async(goal,
            feedback_callback=lambda message: feedback.append(message.feedback)))
        if not handle.accepted:
            raise RuntimeError('Expected reachable goal was rejected')
        return dict(handle=handle, goal_id=bytes(handle.goal_id.uuid).hex(), wall=wall,
                    feedback=feedback, target=list(target))

    def finish(self, sent):
        response = self.client.result(sent['handle'].get_result_async())
        return dict(goal_id=sent['goal_id'], status=response.status, success=response.result.success,
            final_error_metres=response.result.final_error, elapsed_simulation_seconds=response.result.elapsed_time,
            elapsed_wall_seconds=time.monotonic()-sent['wall'], message=response.result.message)

    def diagnostic(self, code, since, goal_id=None):
        matches = [(wall, message) for wall, message in self.messages['diagnostic'][since:]
                   if message.reason_code == code and (goal_id is None or message.goal_id == goal_id)]
        return matches[0] if matches else None

    def wait_diagnostic(self, code, since, goal_id=None):
        self.client.wait(lambda: self.diagnostic(code, since, goal_id) is not None)
        return self.diagnostic(code, since, goal_id)


def demo_scenarios(session):
    """Expected diagnostics are successes of the test, not proof of robot robustness."""
    session.ready()
    rows = []
    session.reset()
    index = len(session.messages['diagnostic'])
    task = session.finish(session.send())
    session.wait_sim(.30)
    codes = [m.reason_code for _, m in session.messages['diagnostic'][index:]]
    if task['status'] != 4 or codes:
        raise RuntimeError('Healthy motion/stationary baseline produced a failure: ' + str(codes))
    rows.append(dict(scenario='healthy_baseline', expected='Successful raw-controlled motion; stationary without alarms',
                     passed=True, observed_codes=codes, task=task))
    session.reset()
    index = len(session.messages['diagnostic'])
    activated = time.monotonic()
    session.configure(stop_publication=True)
    wall, diagnostic = session.wait_diagnostic('STALE_OBSERVATIONS', index)
    latency = wall-activated
    if latency > .35:
        raise RuntimeError(f'Missing-data latency {latency} exceeds 0.35 steady seconds')
    session.configure()
    session.wait_diagnostic('OBSERVATIONS_RECOVERED', index)
    rows.append(dict(scenario='missing_observations', expected='Stale diagnostic then valid-observation recovery',
        passed=True, observed_codes=[m.reason_code for _, m in session.messages['diagnostic'][index:]],
        detection_latency_wall_seconds=latency, detection_bound_wall_seconds=.35, task=None))
    session.reset()
    index = len(session.messages['diagnostic'])
    session.configure(freeze=True)
    sent = session.send()
    wall, diagnostic = session.wait_diagnostic('NO_PROGRESS', index, sent['goal_id'])
    if diagnostic.window_simulation_seconds > .26 or diagnostic.observation_age_steady_seconds > .15:
        raise RuntimeError('Frozen observation detection outside progress/freshness bounds')
    session.configure()
    session.wait_diagnostic('PROGRESS_RECOVERED', index, sent['goal_id'])
    task = session.finish(sent)
    rows.append(dict(scenario='frozen_observations', expected='NO_PROGRESS with fresh messages; recovery on movement',
        passed=task['status'] == 4, observed_codes=[m.reason_code for _, m in session.messages['diagnostic'][index:]],
        detection_latency_simulation_seconds=diagnostic.window_simulation_seconds,
        detection_latency_wall_seconds=wall-sent['wall'], detection_bound_simulation_seconds=.26,
        task=task, limitation='Raw controller succeeds; monitor cannot prove the sensor is frozen'))
    session.reset()
    index = len(session.messages['diagnostic'])
    session.configure(command_delay_seconds=.60)
    sent = session.send()
    _, diagnostic = session.wait_diagnostic('NO_PROGRESS', index, sent['goal_id'])
    session.wait_diagnostic('PROGRESS_RECOVERED', index, sent['goal_id'])
    task = session.finish(sent)
    applied = [m for _, m in session.messages['command'] if m.goal_id == sent['goal_id'] and
               m.operation == 0 and m.event == 'APPLIED'][-1]
    delay = applied.applied_simulation_time-applied.enqueued_simulation_time
    rows.append(dict(scenario='delayed_commands', expected='NO_PROGRESS during queue wait, then motion recovery',
        passed=task['status'] == 4 and .60-1e-9 <= delay <= .68,
        observed_codes=[m.reason_code for _, m in session.messages['diagnostic'][index:]],
        commanded_delay_simulation_seconds=.60, actual_delay_simulation_seconds=delay,
        detection_latency_simulation_seconds=diagnostic.window_simulation_seconds, task=task))
    session.reset()
    session.configure(command_delay_seconds=.70)
    session.parameter('task_timeout', .15)
    sent = session.send()
    task = session.finish(sent)
    session.wait_sim(.80)
    target_events = [m for _, m in session.messages['command'] if m.goal_id == sent['goal_id'] and m.operation == 0]
    rows.append(dict(scenario='queued_timeout', expected='Action abort and purge before target reaches simulator',
        passed=task['status'] == 6 and any(m.event == 'PURGED' for m in target_events)
               and not any(m.event == 'FORWARDED' for m in target_events),
        observed_codes=[], task=task))
    session.parameter('task_timeout', 5.)
    session.configure()
    session.reset()
    index = len(session.messages['diagnostic'])
    task = session.finish(session.send((.50, -.08, .55)))
    session.wait_sim(.10)
    codes = [m.reason_code for _, m in session.messages['diagnostic'][index:]]
    rows.append(dict(scenario='recovery', expected='Faults disabled, healthy action and no diagnostic alarms',
                     passed=task['status'] == 4 and not codes, observed_codes=codes, task=task))
    if not all(row['passed'] for row in rows):
        raise RuntimeError('A fault scenario failed its expected diagnostic/task result')
    return rows
