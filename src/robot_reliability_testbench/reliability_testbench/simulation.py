"""Headless position-only reaching, adapted from robotics_dataset/franka.py.

Uses damped Jacobian IK and upstream position actuators with bias compensation.
No hardware drivers or network robot interfaces.
"""
import hashlib
import json
from pathlib import Path

import mujoco
import numpy as np

MODEL = Path(__file__).resolve().parents[1] / 'models/franka_emika_panda'
if not MODEL.exists():
    from ament_index_python.packages import get_package_share_directory
    MODEL = Path(get_package_share_directory('robot_reliability_testbench')) / 'models/franka_emika_panda'


class PandaSimulation:
    def __init__(self, initial_joints=None):
        source = json.loads((MODEL / 'SOURCE.json').read_text())
        for name, digest in source['files_sha256'].items():
            if hashlib.sha256((MODEL / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f'Model checksum mismatch: {name}')
        self.model = mujoco.MjModel.from_xml_path(str(MODEL / 'panda_nohand.xml'))
        self.data = mujoco.MjData(self.model)
        self.ik = mujoco.MjData(self.model)
        self.site = self.model.site('attachment_site').id
        self.initial_joints = (self.model.key_qpos[0].copy() if initial_joints is None
                               else np.asarray(initial_joints, dtype=float))
        if (self.initial_joints.shape != (7,) or not np.isfinite(self.initial_joints).all()
                or np.any(self.initial_joints < self.model.jnt_range[:, 0])
                or np.any(self.initial_joints > self.model.jnt_range[:, 1])):
            raise ValueError('Initial configuration must be seven finite joints within model limits')
        self.reset()

    def reset(self):
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[:] = self.initial_joints
        self.data.ctrl[:] = self.initial_joints
        mujoco.mj_forward(self.model, self.data)
        self.target = self.position.copy()
        self.qgoal = self.data.qpos.copy()

    @property
    def position(self):
        return self.data.site_xpos[self.site].copy()

    def set_target(self, target):
        target = np.asarray(target, dtype=float)
        if target.shape != (3,) or not np.isfinite(target).all():
            raise ValueError('Target must contain three finite coordinates')
        if np.any(np.abs(target) > 1.5):
            raise ValueError('Target outside conservative Panda workspace bounds')
        q = self.data.qpos.copy()
        for _ in range(200):
            self.ik.qpos[:] = q
            mujoco.mj_forward(self.model, self.ik)
            error = target - self.ik.site_xpos[self.site]
            if np.linalg.norm(error) < 1e-5:
                break
            jac = np.zeros((3, self.model.nv))
            mujoco.mj_jacSite(self.model, self.ik, jac, None, self.site)
            dq = jac.T @ np.linalg.solve(jac @ jac.T + .03**2 * np.eye(3), error)
            q = np.clip(q + np.clip(dq, -.04, .04),
                        self.model.jnt_range[:, 0] + .005,
                        self.model.jnt_range[:, 1] - .005)
        self.ik.qpos[:] = q
        mujoco.mj_forward(self.model, self.ik)
        residual = np.linalg.norm(target - self.ik.site_xpos[self.site])
        if not np.isfinite(q).all() or not np.isfinite(residual) or residual > .001:
            raise ValueError('Target not reachable by bounded IK')
        self.target = target.copy()
        self.qgoal = q

    def advance(self, steps=10):
        for _ in range(steps):
            self.data.ctrl[:] = self.qgoal
            self.data.qfrc_applied[:] = self.data.qfrc_bias
            mujoco.mj_step(self.model, self.data)
        mujoco.mj_forward(self.model, self.data)
        if not np.isfinite(self.data.qpos).all():
            raise RuntimeError('Nonfinite simulation state')
