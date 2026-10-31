"""Bounded ROS transport and physical simulation smoke test: python -m ...demo."""
import json
import platform
import time
from pathlib import Path

import mujoco
import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import JointState

from .simulation import PandaSimulation


class SimulatorNode(Node):
    def __init__(self):
        super().__init__('panda_simulator', namespace='testbench')
        self.sim = PandaSimulation()
        self.joints = self.create_publisher(JointState, 'raw/joint_states', 10)
        self.pose = self.create_publisher(PoseStamped, 'raw/ee_pose', 10)
        self.timer = self.create_timer(.02, self.tick)

    def tick(self):
        self.sim.advance()
        stamp = self.get_clock().now().to_msg()
        joints = JointState()
        joints.header.stamp = stamp
        joints.header.frame_id = 'world'
        joints.name = [f'joint{i}' for i in range(1, 8)]
        joints.position = self.sim.data.qpos.tolist()
        joints.velocity = self.sim.data.qvel.tolist()
        self.joints.publish(joints)
        pose = PoseStamped()
        pose.header = joints.header
        pose.pose.position.x, pose.pose.position.y, pose.pose.position.z = self.sim.position.tolist()
        quat = np.empty(4)
        mujoco.mju_mat2Quat(quat, self.sim.data.site_xmat[self.sim.site])
        pose.pose.orientation.w, pose.pose.orientation.x, pose.pose.orientation.y, pose.pose.orientation.z = quat.tolist()
        self.pose.publish(pose)


def main():
    rclpy.init()
    simulator = SimulatorNode()
    observer = Node('milestone_a_observer', namespace='testbench')
    executor = SingleThreadedExecutor()
    executor.add_node(simulator)
    executor.add_node(observer)
    poses, joints = [], []
    observer.create_subscription(PoseStamped, 'raw/ee_pose', poses.append, 10)
    observer.create_subscription(JointState, 'raw/joint_states', joints.append, 10)
    def wait_until(predicate, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            executor.spin_once(timeout_sec=.02)
            if predicate():
                return True
        return False
    try:
        if not wait_until(lambda: len(poses) >= 2 and len(joints) >= 2, 5):
            raise RuntimeError('ROS state readiness timed out')
        initial = simulator.sim.position
        target = initial + np.array([.04, .03, -.03])
        simulator.sim.set_target(target)
        start = time.monotonic()
        def observed_error():
            p = poses[-1].pose.position
            return float(np.linalg.norm(np.array([p.x, p.y, p.z]) - target))
        success = wait_until(lambda: observed_error() <= .005, 5)
        result = dict(milestone='A', success=success, target_metres=target.tolist(),
                      initial_metres=initial.tolist(), final_error_metres=observed_error(),
                      tolerance_metres=.005, timeout_seconds=5,
                      completion_wall_seconds=time.monotonic() - start,
                      pose_messages=len(poses), joint_messages=len(joints),
                      simulation_seconds=simulator.sim.data.time,
                      python=platform.python_version(), mujoco=mujoco.__version__,
                      platform=platform.platform(), ros_distro='jazzy')
        Path('reports').mkdir(exist_ok=True)
        Path('reports/milestone_a.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
        if not success:
            raise RuntimeError('Reach did not meet tolerance before deadline')
    finally:
        executor.shutdown()
        observer.destroy_node()
        simulator.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
