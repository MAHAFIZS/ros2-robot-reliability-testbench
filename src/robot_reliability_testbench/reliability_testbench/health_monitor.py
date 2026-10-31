"""ROS adapter: only affected observations, intent and /clock are inputs."""
import math
import time
import uuid

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import QoSProfile
from rosgraph_msgs.msg import Clock as ClockMessage
from reliability_interfaces.msg import ObservedState, TaskIntent, DiagnosticEvent
from reliability_interfaces.srv import MonitorStatus

from .monitor_core import MonitorCore
from .time_utils import sim_stamp
from .timing_trace import Trace


class HealthMonitor(Node):
    def __init__(self, replay=False):
        super().__init__('replay_health_monitor' if replay else 'health_monitor',
                         namespace='replay' if replay else 'testbench')
        readonly = ParameterDescriptor(read_only=True)
        self.timing = Trace.from_environment('monitor')
        values = {}
        for name, default in [('freshness_seconds', .15), ('progress_window_seconds', .20),
                              ('movement_threshold_metres', .001), ('startup_grace_seconds', .30)]:
            value = self.declare_parameter(name, default, readonly).value
            if not math.isfinite(value) or value <= 0:
                raise ValueError(name + ' must be finite and positive')
            values[name] = value
        self.session = uuid.uuid4().hex
        self.diagnostic_count = 0
        self.replay = replay
        self.replay_armed = not replay
        self.received_counts = dict(observation=0, intent=0, clock=0)
        self.publisher = self.create_publisher(DiagnosticEvent,
            '/replay/diagnostics' if replay else '/testbench/diagnostics', QoSProfile(depth=1000))
        self.core = MonitorCore(self.emit, time.monotonic(), values['freshness_seconds'],
            values['progress_window_seconds'], values['movement_threshold_metres'], values['startup_grace_seconds'])
        self.create_subscription(ObservedState, '/testbench/observed/state', self.observe, QoSProfile(depth=1000))
        self.create_subscription(TaskIntent, '/testbench/task_intent', self.intent, QoSProfile(depth=1000))
        self.create_subscription(ClockMessage, '/clock', self.clock, QoSProfile(depth=1000))
        self.create_service(MonitorStatus, '/replay/monitor_status' if replay else '/testbench/observation_health', self.status)
        self.timer = self.create_timer(.01, lambda: self.core.tick(time.monotonic()),
                                      clock=Clock(clock_type=ClockType.STEADY_TIME))
        if replay:
            self.timer.cancel()  # Arm only after subscriber/player readiness.

    def clock(self, message):
        self.received_counts['clock'] += 1
        self.core.clock = message.clock.sec + message.clock.nanosec / 1e9

    def observe(self, message):
        entry_ns = time.monotonic_ns() if self.timing else 0
        if self.timing:
            self.timing.observe(message, entry_ns)
        if self.replay and not self.replay_armed:
            # Recorder subscriptions attach separately. A bag may begin with clock/
            # intent before its first affected sample, although the live monitor
            # already had a baseline. Do not diagnose that incomplete capture prefix.
            self.core.started = time.monotonic()
            self.timer.reset()
            self.replay_armed = True
        self.received_counts['observation'] += 1
        p = message.position
        self.core.observe(dict(generation=message.generation, sequence=message.sequence,
            time=message.simulation_time, position=[p.x, p.y, p.z], joints=list(message.joint_positions)), time.monotonic())

    def intent(self, message):
        self.received_counts['intent'] += 1
        p = message.target
        self.core.task_intent(dict(generation=message.generation, active=message.active,
            goal_id=message.goal_id, target=[p.x, p.y, p.z], tolerance=message.tolerance), time.monotonic())

    def emit(self, evidence):
        self.diagnostic_count += 1
        evidence = dict(evidence)
        stamp = evidence.pop('simulation_time')
        self.publisher.publish(DiagnosticEvent(stamp=sim_stamp(stamp), monitor_session=self.session,
            sequence=self.diagnostic_count, **evidence))

    def status(self, request, response):
        obs = self.core.observation
        response.ready = obs is not None
        response.active_reasons = sorted(self.core.alerts)
        response.observations = self.core.observations
        response.diagnostics = self.diagnostic_count
        response.observation_age_steady_seconds = (-1. if self.core.received is None else
                                                   time.monotonic()-self.core.received)
        if obs:
            response.generation = obs['generation']
            response.observation_sequence = obs['sequence']
        return response


def main():
    rclpy.init()
    node = HealthMonitor()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if node.timing:
            node.timing.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
