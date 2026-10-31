"""Single-threaded action orchestration. Await futures; never block the executor."""
import math
import time
import uuid

import numpy as np
import rclpy
from rcl_interfaces.msg import ParameterDescriptor, SetParametersResult
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.task import Future
from reliability_interfaces.action import Reach
from reliability_interfaces.msg import SimulationState, TaskEvent, TaskIntent
from geometry_msgs.msg import Point
from rclpy.qos import QoSProfile
from reliability_interfaces.srv import Control, Health, Reset

from .simulation import PandaSimulation
from .time_utils import sim_stamp


class TaskServer(Node):
    def __init__(self):
        super().__init__('task_server', namespace='testbench')
        self.declare_parameter('target_tolerance', .005)
        readonly = ParameterDescriptor(read_only=True)
        self.declare_parameter('task_timeout', 5.)
        self.watchdog = self.declare_parameter('infrastructure_timeout', 3., readonly).value
        for name in ['target_tolerance', 'task_timeout', 'infrastructure_timeout']:
            value = self.get_parameter(name).value
            if not isinstance(value, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        self.add_on_set_parameters_callback(self.validate_parameters)
        self.validator = PandaSimulation()
        self.state = None
        self.state_wall = None
        self.active = None
        self.busy = False
        self.resetting = False
        self.sequence = 0
        self.minimum_generation = 0
        self.event_sequence = 0
        self.event_session = uuid.uuid4().hex
        self.events = self.create_publisher(TaskEvent, 'task_events', QoSProfile(depth=1000))
        self.intent = self.create_publisher(TaskIntent, 'task_intent', QoSProfile(depth=1000))
        self.group = ReentrantCallbackGroup()
        self.control_client = self.create_client(Control, 'boundary/control')
        self.reset_client = self.create_client(Reset, 'boundary/reset')
        self.create_subscription(SimulationState, 'simulation_state', self.receive_state, 10)
        self.create_service(Health, 'health', self.health)
        self.create_service(Reset, 'reset', self.reset, callback_group=self.group)
        self.server = ActionServer(self, Reach, 'reach', execute_callback=self.execute,
            goal_callback=self.goal, cancel_callback=self.cancel,
            handle_accepted_callback=self.accepted, callback_group=self.group)
        self.create_timer(.02, self.tick, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def validate_parameters(self, parameters):
        for parameter in parameters:
            if parameter.name in ('target_tolerance', 'task_timeout'):
                value = parameter.value
                if not isinstance(value, float) or not math.isfinite(value) or value <= 0:
                    return SetParametersResult(successful=False,
                                               reason=parameter.name + ' must be finite and positive')
        return SetParametersResult(successful=True)

    def receive_state(self, state):
        if state.generation < self.minimum_generation:
            return
        self.state = state
        self.state_wall = time.monotonic()

    def ready(self):
        return (self.state is not None and self.state_wall is not None
                and time.monotonic() - self.state_wall < self.watchdog
                and self.control_client.service_is_ready() and self.reset_client.service_is_ready())

    def health(self, request, response):
        response.ready = self.ready()
        response.resetting = self.resetting
        response.active_goal = self.busy
        response.state_age_wall_seconds = (-1. if self.state_wall is None
                                           else time.monotonic() - self.state_wall)
        response.healthy = bool(response.ready and not self.resetting and
            np.isfinite(self.state.joint_positions).all() and
            np.isfinite([self.state.position.x, self.state.position.y, self.state.position.z]).all())
        if self.state is not None:
            response.simulation_time = self.state.simulation_time
            response.generation = self.state.generation
        response.message = 'Ready' if response.healthy else 'Not ready, resetting, stale or invalid state'
        return response

    def goal(self, request):
        if self.busy or self.resetting or not self.ready():
            return GoalResponse.REJECT
        p = request.target
        try:
            # Dry-run IK only. Actual simulator validates again against its state.
            self.validator.data.qpos[:] = self.state.joint_positions
            self.validator.set_target([p.x, p.y, p.z])
        except ValueError:
            return GoalResponse.REJECT
        self.busy = True  # Reserve before acknowledging acceptance.
        return GoalResponse.ACCEPT

    def command(self, operation, target=None, goal_id=None):
        self.sequence += 1
        request = Control.Request(operation=operation,
            generation=self.state.generation, sequence=self.sequence)
        request.goal_id = (goal_id if goal_id is not None else
                           bytes(self.active['handle'].goal_id.uuid).hex() if self.active else '')
        if target is not None:
            request.target = target
        return self.control_client.call_async(request)

    def accepted(self, handle):
        p = handle.request.target
        target = np.array([p.x, p.y, p.z])
        position = self.state.position
        initial_error = float(np.linalg.norm(target - [position.x, position.y, position.z]))
        self.active = dict(handle=handle, future=Future(), target=target,
            initial_error=initial_error, error=initial_error, elapsed=0.,
            timeout=self.get_parameter('task_timeout').value,
            generation=self.state.generation, started=self.state.simulation_time, wall=time.monotonic(),
            snapshot_position=position, snapshot_time=self.state.simulation_time,
            command=self.command(Control.Request.TARGET, p, bytes(handle.goal_id.uuid).hex()), stopping=None)
        handle.testbench_context = self.active
        self.emit_event('ACCEPTED', self.active)
        self.emit_event('TARGET', self.active)
        self.publish_intent()
        handle.execute()

    def emit_event(self, event, context=None, outcome='', detail='', reset_response=None):
        self.event_sequence += 1
        message = TaskEvent(session_id=self.event_session, sequence=self.event_sequence,
                            event=event, outcome=outcome, detail=detail,
                            tolerance=self.get_parameter('target_tolerance').value)
        if context is not None:
            message.goal_id = bytes(context['handle'].goal_id.uuid).hex()
            message.generation = context['generation']
            message.stamp = sim_stamp(context['snapshot_time'])
            message.target = Point(x=float(context['target'][0]), y=float(context['target'][1]),
                                   z=float(context['target'][2]))
            message.has_position = True
            message.position = context['snapshot_position']
            message.final_error = context['error']
            message.elapsed_simulation_seconds = context['elapsed']
            message.elapsed_wall_seconds = time.monotonic() - context['wall']
        else:
            message.goal_id = 'reset:' + uuid.uuid4().hex
        if reset_response is not None:
            message.generation = reset_response.generation
            message.stamp = sim_stamp(reset_response.simulation_time)
            message.has_position = False
        self.events.publish(message)

    async def execute(self, handle):
        # The context belongs to this handle even if another goal is later accepted.
        context = handle.testbench_context
        return await context['future']

    def cancel(self, handle):
        return CancelResponse.ACCEPT if self.active and self.active['handle'] is handle else CancelResponse.REJECT

    def finish(self, context, outcome, message):
        if context['future'].done():
            return
        handle = context['handle']
        if outcome == 'success':
            handle.succeed()
        elif outcome == 'cancel':
            handle.canceled()
        else:
            handle.abort()
        terminal_outcome = ('succeeded' if outcome == 'success' else 'canceled' if outcome == 'cancel'
                            else 'timeout' if message.startswith('Simulation task timeout')
                            else 'reset' if 'reset' in message.lower() else 'aborted')
        marker = {'canceled': 'CANCELED', 'timeout': 'TIMEOUT', 'reset': 'ABORTED', 'aborted': 'ABORTED'}
        if terminal_outcome in marker:
            self.emit_event(marker[terminal_outcome], context, terminal_outcome, message)
        self.emit_event('COMPLETED', context, terminal_outcome, message)
        context['future'].set_result(Reach.Result(success=outcome == 'success',
            final_error=context['error'], elapsed_time=context['elapsed'], message=message))
        if self.active is context:
            self.active = None
            self.busy = False

    def stop(self, context, outcome, message):
        # A higher sequence hold supersedes an in-flight target command.
        context['stopping'] = (self.command(Control.Request.HOLD), outcome, message, time.monotonic())

    def terminal_snapshot(self, context, position, simulation_time):
        context['snapshot_position'] = position
        context['snapshot_time'] = simulation_time
        if context['started'] is not None:
            context['elapsed'] = max(0., simulation_time - context['started'])
        context['error'] = float(np.linalg.norm(context['target'] - [position.x, position.y, position.z]))

    def tick(self):
        self.publish_intent()
        c = self.active
        if c is None or self.resetting:
            return
        now = time.monotonic()
        if c['stopping'] is not None:
            future, outcome, message, started = c['stopping']
            if future.done():
                response = future.result()
                self.terminal_snapshot(c, response.position, response.simulation_time)
                self.finish(c, outcome, message if response.accepted else message + '; hold rejected')
            elif now - started > self.watchdog:
                self.finish(c, 'abort', 'Infrastructure watchdog: hold not acknowledged')
            return
        if c['handle'].is_cancel_requested:
            self.stop(c, 'cancel', 'Canceled; holding current joint positions')
            return
        if not self.ready():
            if now - (self.state_wall or c['wall']) > self.watchdog:
                self.stop(c, 'abort', 'Infrastructure watchdog: missing simulation state')
            return
        if self.state.generation != c['generation']:
            self.finish(c, 'abort', 'Simulation reset')
            return
        c['elapsed'] = max(0., self.state.simulation_time - c['started'])
        if c['elapsed'] >= c['timeout']:
            self.stop(c, 'abort', 'Simulation task timeout')
            return
        if not c['command'].done():
            if now - c['wall'] > self.watchdog:
                self.stop(c, 'abort', 'Infrastructure watchdog: command not acknowledged')
            return
        response = c['command'].result()
        if not response.accepted:
            self.finish(c, 'abort', 'Simulator rejected command: ' + response.message)
            return
        # A state queued before the command acknowledgement is not task progress.
        if self.state.simulation_time < c['started']:
            return
        c['elapsed'] = max(0., self.state.simulation_time - c['started'])
        p = self.state.position
        c['snapshot_position'] = p
        c['snapshot_time'] = self.state.simulation_time
        c['error'] = float(np.linalg.norm(c['target'] - [p.x, p.y, p.z]))
        feedback = Reach.Feedback(distance=c['error'], elapsed_time=c['elapsed'],
            progress=float(np.clip(1 - c['error'] / max(c['initial_error'], 1e-12), 0., 1.)))
        c['handle'].publish_feedback(feedback)
        if c['elapsed'] >= c['timeout']:
            self.stop(c, 'abort', 'Simulation task timeout')
        elif c['error'] <= self.get_parameter('target_tolerance').value:
            self.finish(c, 'success', 'Target reached')

    def publish_intent(self):
        if self.state is None:
            return
        c = self.active
        message = TaskIntent(stamp=sim_stamp(self.state.simulation_time), generation=self.state.generation,
            active=c is not None and c['stopping'] is None and not self.resetting,
            tolerance=self.get_parameter('target_tolerance').value)
        if c is not None:
            message.goal_id = bytes(c['handle'].goal_id.uuid).hex()
            message.target = Point(x=float(c['target'][0]), y=float(c['target'][1]), z=float(c['target'][2]))
        self.intent.publish(message)

    async def reset(self, request, response):
        if self.resetting or not self.reset_client.service_is_ready():
            response.message = 'Reset already in progress or simulator unavailable'
            return response
        self.resetting = True
        context = self.active
        future = self.reset_client.call_async(Reset.Request())
        # A steady timer bounds reset even when /clock or simulator stops.
        timeout_future = Future()
        def expire():
            if not timeout_future.done():
                timeout_future.set_result(None)
        timer = self.create_timer(self.watchdog, expire,
                                 clock=Clock(clock_type=ClockType.STEADY_TIME))
        future.add_done_callback(lambda done: expire())
        try:
            await timeout_future
            if future.done():
                result = future.result()
                response.success = result.success
                response.message = result.message
                response.generation = result.generation
                response.simulation_time = result.simulation_time
                response.joint_positions = result.joint_positions
                response.previous_simulation_time = result.previous_simulation_time
                response.previous_position = result.previous_position
                self.minimum_generation = result.generation
                # Require a post-reset observation before accepting a new target.
                if self.state is None or self.state.generation < result.generation:
                    self.state_wall = None
            else:
                response.message = 'Infrastructure watchdog: reset not acknowledged'
            if context is not None:
                if future.done() and response.success:
                    self.terminal_snapshot(context, response.previous_position,
                                           response.previous_simulation_time)
                self.finish(context, 'abort', 'Reset requested; active goal terminated')
            if response.success:
                self.emit_event('RESET', context, detail=response.message, reset_response=response)
        finally:
            self.destroy_timer(timer)
            self.resetting = False
        return response


def main():
    rclpy.init()
    node = TaskServer()
    try:
        # Deliberately single-threaded: callbacks mutate lifecycle state serially.
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
