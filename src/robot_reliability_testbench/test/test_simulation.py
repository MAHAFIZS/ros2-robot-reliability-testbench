import numpy as np
import pytest
from reliability_testbench.simulation import PandaSimulation


def test_reach_with_physics():
    sim = PandaSimulation()
    target = sim.position + [.04, .03, -.03]
    sim.set_target(target)
    for _ in range(250):
        sim.advance()
    assert np.linalg.norm(sim.position - target) < .005
    assert np.all(sim.data.qpos >= sim.model.jnt_range[:, 0])
    assert np.all(sim.data.qpos <= sim.model.jnt_range[:, 1])


@pytest.mark.parametrize('target', [[float('nan'), 0, 0], [1, 2], [10, 10, 10]])
def test_reject_invalid_or_unreachable_target(target):
    sim = PandaSimulation()
    before = sim.target.copy()
    with pytest.raises(ValueError):
        sim.set_target(target)
    np.testing.assert_array_equal(sim.target, before)


def test_configured_initial_state_and_reset():
    initial = [0., -.2, 0., -1.8, 0., 1.7, -.7]
    sim = PandaSimulation(initial)
    sim.set_target(sim.position + [.02, .02, -.02])
    sim.advance(100)
    sim.reset()
    np.testing.assert_array_equal(sim.data.qpos, initial)
    np.testing.assert_array_equal(sim.data.qvel, np.zeros(7))
    np.testing.assert_array_equal(sim.data.ctrl, initial)
    assert sim.data.time == 0.


@pytest.mark.parametrize('initial', [[0.] * 7, [float('nan')] * 7, [0.] * 6])
def test_invalid_initial_state(initial):
    with pytest.raises(ValueError):
        PandaSimulation(initial)
