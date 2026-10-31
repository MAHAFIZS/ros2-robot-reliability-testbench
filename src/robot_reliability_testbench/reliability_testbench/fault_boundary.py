"""Serialized observation faults and a bounded FIFO before simulator commands."""
from collections import deque
import copy
import math
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rclpy.qos import QoSProfile
from rclpy.task import Future
from sensor_msgs.msg import JointState
from reliability_interfaces.msg import (SimulationState, ObservedState, FaultConfiguration,
                                        FaultEvent, CommandEvent)
from reliability_interfaces.srv import Control, ConfigureFaults, Reset

from .time_utils import sim_stamp
from .timing_trace import Trace, stamp_ns


MAX_DELAY = 2.0
MAX_CAPACITY = 64
MAX_QUEUE_RESIDENCE = 2.10  # Includes quantization/backlog beyond the configured <=2 s delay.


def validate_configuration(config):
    if config.drop_every_n > 1000:
        raise ValueError('drop_every_n must be within [0, 1000]')
    if not math.isfinite(config.command_delay_seconds) or not 0 <= config.command_delay_seconds <= MAX_DELAY:
        raise ValueError('command_delay_seconds must be finite within [0, 2] simulation seconds')
    if not 1 <= config.queue_capacity <= MAX_CAPACITY:
        raise ValueError('queue_capacity must be within [1, 64]')


class FaultBoundary(Node):
    def __init__(self):
        super().__init__('fault_boundary', namespace='testbench')
        self.timing = Trace.from_environment('boundary')
        self.config = FaultConfiguration()
        self.revision = 0
        self.generation = 0
        self.simulation_time = 0.
        self.source_sequence = 0
        self.phases = {}
        self.last_raw = {}
        self.frozen = {}
        self.queue = deque()
        self.inflight = None
        self.sequence = 0
        self.resetting = False
        self.group = ReentrantCallbackGroup()
        qos = QoSProfile(depth=1000)
        self.observed = self.create_publisher(ObservedState, 'observed/state', qos)
        self.joints = self.create_publisher(JointState, 'observed/joint_states', qos)
        self.pose = self.create_publisher(PoseStamped, 'observed/ee_pose', qos)
        self.fault_events = self.create_publisher(FaultEvent, 'fault_events', qos)
        self.command_events = self.create_publisher(CommandEvent, 'command_events', qos)
        self.create_subscription(SimulationState, 'simulation_state', self.raw_state, qos)
        self.create_subscription(JointState, 'raw/joint_states',
            lambda msg: self.raw_aux('joints', msg, self.joints), qos)
        self.create_subscription(PoseStamped, 'raw/ee_pose',
            lambda msg: self.raw_aux('pose', msg, self.pose), qos)
        self.sim_control = self.create_client(Control, 'internal/control')
        self.sim_reset = self.create_client(Reset, 'internal/reset')
        self.create_service(Control, 'boundary/control', self.control, callback_group=self.group)
        self.create_service(Reset, 'boundary/reset', self.reset, callback_group=self.group)
        self.create_service(ConfigureFaults, 'configure_faults', self.configure)
        self.create_timer(.005, self.dispatch, clock=Clock(clock_type=ClockType.STEADY_TIME))

    def filter_values(self, key, message):
        self.last_raw[key] = copy.deepcopy(message)
        self.phases[key] = self.phases.get(key, 0) + 1
        if self.config.stop_publication or (self.config.drop_every_n and
                                             self.phases[key] % self.config.drop_every_n == 0):
            return None
        if not self.config.freeze:
            return message
        if key not in self.frozen:
            self.frozen[key] = copy.deepcopy(message)
        frozen = copy.deepcopy(self.frozen[key])
        if key == 'state':
            # Freeze values only: source identity and simulation timestamps keep advancing.
            frozen.stamp, frozen.sequence = message.stamp, message.sequence
            frozen.simulation_time, frozen.generation = message.simulation_time, message.generation
        else:
            frozen.header = message.header
        return frozen

    def raw_aux(self, key, message, publisher):
        result = self.filter_values(key, message)
        if result is not None:
            publisher.publish(result)

    def raw_state(self, message):
        entry_ns = time.monotonic_ns() if self.timing else 0
        if message.generation < self.generation:
            return
        if message.generation != self.generation:
            self.generation = message.generation
            self.source_sequence = 0
            self.sequence = 0
        self.simulation_time = message.simulation_time
        self.source_sequence += 1
        observed = ObservedState(stamp=message.stamp, generation=message.generation,
            sequence=self.source_sequence, simulation_time=message.simulation_time,
            position=message.position, joint_positions=message.joint_positions)
        result = self.filter_values('state', observed)
        if result is not None:
            start_ns = time.monotonic_ns() if self.timing else 0
            self.observed.publish(result)
            if self.timing:
                end_ns = time.monotonic_ns()
                self.timing.emit('boundary', generation=result.generation,
                    sequence=result.sequence, simulation_stamp_ns=stamp_ns(result),
                    entry_ns=entry_ns, publish_start_ns=start_ns, publish_end_ns=end_ns)
        self.dispatch()

    def event(self, job, event, detail='', applied=None):
        request = job['request']
        self.command_events.publish(CommandEvent(stamp=sim_stamp(self.simulation_time if applied is None else applied),
            generation=request.generation, sequence=request.sequence, goal_id=request.goal_id,
            operation=request.operation, event=event, enqueued_simulation_time=job['enqueued'],
            target=request.target,
            due_simulation_time=job['due'], applied_simulation_time=0. if applied is None else applied,
            pending_count=len(self.queue) + int(self.inflight is not None), detail=detail))

    def reject_response(self, detail):
        return Control.Response(accepted=False, message=detail, generation=self.generation,
                                simulation_time=self.simulation_time)

    def purge(self, reason):
        # Pending targets are resolved immediately. In-flight simulator requests are
        # fenced by the subsequent higher-sequence HOLD or generation-changing reset.
        jobs = list(self.queue)
        self.queue.clear()
        if self.inflight is not None:
            jobs.append(self.inflight)
            self.inflight = None
        for job in jobs:
            self.event(job, 'PURGED', reason)
            if not job['future'].done():
                job['future'].set_result(self.reject_response(reason))

    def configure(self, request, response):
        try:
            validate_configuration(request.configuration)
            if self.resetting:
                raise ValueError('Reset in progress')
        except ValueError as exc:
            response.message = str(exc)
        else:
            # Reconfiguration cancels queued requests; due times never silently change.
            for job in list(self.queue):
                self.event(job, 'PURGED', 'Fault configuration changed')
                job['future'].set_result(self.reject_response('Fault configuration changed'))
            self.queue.clear()
            self.set_config(request.configuration, 'CONFIGURED')
            response.accepted = True
            response.message = 'Configuration applied; pending queued targets canceled'
        response.revision = self.revision
        response.configuration = self.config
        response.pending_commands = len(self.queue) + int(self.inflight is not None)
        response.observation_sequence = self.source_sequence
        return response

    def set_config(self, configuration, event):
        previous = self.config
        fields = ['drop_every_n', 'freeze', 'stop_publication', 'command_delay_seconds']
        activated = [f for f in fields if getattr(configuration, f) and not getattr(previous, f)]
        deactivated = [f for f in fields if getattr(previous, f) and not getattr(configuration, f)]
        self.config = copy.deepcopy(configuration)
        self.revision += 1
        self.phases.clear()
        self.frozen = copy.deepcopy(self.last_raw) if self.config.freeze else {}
        self.fault_events.publish(FaultEvent(stamp=sim_stamp(self.simulation_time),
            generation=self.generation, revision=self.revision, event=event, activated=activated,
            deactivated=deactivated, previous=previous, configuration=self.config,
            detail='Fixed deterministic faults; seed is metadata, no random draws'))

    async def control(self, request, response):
        if (self.resetting or request.generation != self.generation or request.sequence <= self.sequence
                or not self.sim_control.service_is_ready()):
            return self.reject_response('Resetting, stale generation/sequence or simulator unavailable')
        self.sequence = request.sequence
        job = dict(request=request, future=Future(), enqueued=self.simulation_time,
                   due=self.simulation_time + self.config.command_delay_seconds)
        if request.operation == Control.Request.HOLD:
            self.purge('Superseded by hold')
            self.event(job, 'FORWARDED', 'Hold bypasses delay')
            result = await self.sim_control.call_async(request)
            self.event(job, 'APPLIED' if result.accepted else 'REJECTED', result.message,
                       applied=result.simulation_time)
            return result
        if request.operation != Control.Request.TARGET:
            return self.reject_response('Unknown control operation')
        if len(self.queue) + int(self.inflight is not None) >= self.config.queue_capacity:
            self.event(job, 'REJECTED', 'Queue full; newest request rejected')
            return self.reject_response('Queue full; newest request rejected')
        self.queue.append(job)
        self.event(job, 'QUEUED')
        self.dispatch()
        return await job['future']

    def dispatch(self):
        if self.resetting:
            return
        while self.queue and self.simulation_time-self.queue[0]['enqueued'] > MAX_QUEUE_RESIDENCE:
            expired = self.queue.popleft()
            self.event(expired, 'EXPIRED', 'Maximum 2.10 s simulation queue residence exceeded')
            expired['future'].set_result(self.reject_response('Maximum queue residence exceeded'))
        if self.inflight is not None or not self.queue:
            return
        job = self.queue[0]
        if self.simulation_time + 1e-9 < job['due']:
            return
        self.queue.popleft()
        if job['request'].generation != self.generation:
            job['future'].set_result(self.reject_response('Generation changed'))
            self.event(job, 'PURGED', 'Generation changed')
            return
        self.inflight = job
        self.event(job, 'FORWARDED')
        forwarded = self.sim_control.call_async(job['request'])
        def done(future):
            result = future.result()
            self.event(job, 'APPLIED' if result.accepted else 'REJECTED', result.message,
                       applied=result.simulation_time)
            if not job['future'].done():
                job['future'].set_result(result)
            if self.inflight is job:
                self.inflight = None
            self.dispatch()
        forwarded.add_done_callback(done)

    async def reset(self, request, response):
        if self.resetting or not self.sim_reset.service_is_ready():
            response.message = 'Reset already pending or simulator unavailable'
            return response
        self.resetting = True
        self.purge('Reset clears pending commands')
        self.set_config(FaultConfiguration(), 'RESET')
        try:
            result = await self.sim_reset.call_async(request)
            if result.success:
                if self.generation != result.generation:
                    self.source_sequence = 0
                self.generation = result.generation
                self.sequence = 0
                self.simulation_time = 0.
                self.frozen.clear()
                self.phases.clear()
            return result
        finally:
            self.resetting = False


def main():
    rclpy.init()
    node = FaultBoundary()
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
