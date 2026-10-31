"""The sole owner of MuJoCo state. All callbacks run serially."""
import math
import time

import mujoco
import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped, Point
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.clock import Clock, ClockType
from rclpy.node import Node
from rosgraph_msgs.msg import Clock as ClockMessage
from sensor_msgs.msg import JointState
from reliability_interfaces.msg import SimulationState
from reliability_interfaces.srv import Control, Reset

from .simulation import PandaSimulation
from .time_utils import sim_stamp
from .timing_trace import Trace, stamp_ns


class SimulatorNode(Node):
    def __init__(self):
        super().__init__('panda_simulator', namespace='testbench')
        readonly = ParameterDescriptor(read_only=True)
        rate = self.declare_parameter('publication_rate', 50.0, readonly).value
        initial = self.declare_parameter('initial_joint_positions',
            [0., 0., 0., -1.57079, 0., 1.57079, -.7853], readonly).value
        if not math.isfinite(rate) or not 1 <= rate <= 500:
            raise ValueError('publication_rate must be finite, within [1, 500] Hz')
        self.sim = PandaSimulation(initial)
        self.timing = Trace.from_environment('simulator')
        self.publication_sequence = 0
        self.generation = 0
        self.sequence = 0
        self.step_credit = 0.0
        self.steps_per_tick = 1 / (rate * self.sim.model.opt.timestep)
        self.joints = self.create_publisher(JointState, 'raw/joint_states', 10)
        self.pose = self.create_publisher(PoseStamped, 'raw/ee_pose', 10)
        self.state = self.create_publisher(SimulationState, 'simulation_state', 10)
        self.clock_pub = self.create_publisher(ClockMessage, '/clock', 10)
        self.create_service(Control, 'internal/control', self.control)
        self.create_service(Reset, 'internal/reset', self.reset)
        # A ROS-time timer would deadlock at startup before the first /clock.
        self.timer = self.create_timer(1 / rate, self.tick,
                                      clock=Clock(clock_type=ClockType.STEADY_TIME))

    def control(self, request, response):
        response.generation = self.generation
        response.simulation_time = self.sim.data.time
        response.position = Point(x=float(self.sim.position[0]), y=float(self.sim.position[1]),
                                  z=float(self.sim.position[2]))
        if request.generation != self.generation or request.sequence <= self.sequence:
            response.message = 'Stale generation or command sequence'
            return response
        self.sequence = request.sequence
        try:
            if request.operation == Control.Request.TARGET:
                p = request.target
                self.sim.set_target([p.x, p.y, p.z])
            elif request.operation == Control.Request.HOLD:
                self.sim.qgoal = self.sim.data.qpos.copy()
                self.sim.target = self.sim.position
            else:
                raise ValueError('Unknown control operation')
        except ValueError as exc:
            response.message = str(exc)
            return response
        response.accepted = True
        response.message = 'Applied'
        return response

    def reset(self, request, response):
        response.previous_simulation_time = self.sim.data.time
        response.previous_position = Point(x=float(self.sim.position[0]), y=float(self.sim.position[1]),
                                           z=float(self.sim.position[2]))
        self.sim.reset()
        self.step_credit = 0.
        self.generation += 1
        self.sequence = 0
        response.success = True
        response.message = 'Initial state restored; simulation time reset to zero'
        response.generation = self.generation
        response.simulation_time = self.sim.data.time
        response.joint_positions = self.sim.data.qpos.tolist()
        self.publish_state()
        return response

    def tick(self):
        entry_ns = time.monotonic_ns() if self.timing else 0
        self.step_credit += self.steps_per_tick
        steps = int(self.step_credit + 1e-9)
        self.step_credit -= steps
        self.sim.advance(steps)
        self.publish_state(entry_ns)

    def publish_state(self, tick_entry_ns=0):
        stamp = sim_stamp(self.sim.data.time)
        self.clock_pub.publish(ClockMessage(clock=stamp))
        joints = JointState()
        joints.header.stamp = stamp
        joints.header.frame_id = 'world'
        joints.name = [f'joint{i}' for i in range(1, 8)]
        joints.position = self.sim.data.qpos.tolist()
        joints.velocity = self.sim.data.qvel.tolist()
        self.joints.publish(joints)
        point = Point(x=float(self.sim.position[0]), y=float(self.sim.position[1]),
                      z=float(self.sim.position[2]))
        pose = PoseStamped()
        pose.header = joints.header
        pose.pose.position = point
        quat = np.empty(4)
        mujoco.mju_mat2Quat(quat, self.sim.data.site_xmat[self.sim.site])
        pose.pose.orientation.w, pose.pose.orientation.x, pose.pose.orientation.y, pose.pose.orientation.z = quat.tolist()
        self.pose.publish(pose)
        message = SimulationState(stamp=stamp, generation=self.generation,
            simulation_time=self.sim.data.time, position=point,
            joint_positions=joints.position)
        self.publication_sequence += 1
        start_ns = time.monotonic_ns() if self.timing else 0
        self.state.publish(message)
        if self.timing:
            end_ns = time.monotonic_ns()
            self.timing.emit('source_publish', generation=self.generation,
                source_sequence=self.publication_sequence, simulation_stamp_ns=stamp_ns(message),
                tick_entry_ns=tick_entry_ns, publish_start_ns=start_ns, publish_end_ns=end_ns)


def main():
    rclpy.init()
    node = SimulatorNode()
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
