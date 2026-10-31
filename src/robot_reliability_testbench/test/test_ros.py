"""Contract tests against the installed two-process Python launch configuration."""
import math

import numpy as np
import pytest
from action_msgs.msg import GoalStatus
from reliability_interfaces.srv import Control
from reliability_interfaces.msg import SimulationState

HOME = [0., 0., 0., -1.57079, 0., 1.57079, -.7853]


@pytest.mark.parametrize('target', [[.5945, .03, .5945], [.50, -.08, .55], [.55, .10, .65]])
def test_ros_success_and_feedback(clean_ros, target):
    ros = clean_ros
    response, feedback = ros.outcome('healthy_reach', ros.send(target))
    assert response.status == GoalStatus.STATUS_SUCCEEDED
    assert response.result.success
    assert response.result.final_error <= .005
    assert 0 <= response.result.elapsed_time < 5
    assert feedback
    assert all(math.isfinite(f.distance) and 0 <= f.progress <= 1 for f in feedback)
    assert feedback[-1].distance <= .005
    assert len(feedback) > 1  # Stepping/publication continued while execute awaited.


@pytest.mark.parametrize('target', [[float('nan'), 0., .5], [0., float('inf'), .5],
                                   [10., 10., 10.], [1e300, 0., .5]])
def test_ros_invalid_goal_rejected(clean_ros, target):
    assert not clean_ros.send(target)[0].accepted
    assert not clean_ros.health().active_goal


def test_ros_cancel(clean_ros):
    sent = clean_ros.send([.45, .25, .45])
    handle = sent[0]
    assert handle.accepted
    clean_ros.wait(lambda: len(sent[1]) >= 2)
    assert clean_ros.health().active_goal
    canceled = clean_ros.result(handle.cancel_goal_async())
    assert canceled.goals_canceling
    response, _ = clean_ros.outcome('cancellation', sent)
    assert response.status == GoalStatus.STATUS_CANCELED
    assert not response.result.success
    assert response.result.elapsed_time > 0.
    assert 'Canceled' in response.result.message
    assert clean_ros.health().healthy
    states = []
    subscription = clean_ros.node.create_subscription(SimulationState, 'simulation_state', states.append, 10)
    try:
        clean_ros.wait(lambda: bool(states))
        start_time = states[-1].simulation_time
        clean_ros.wait(lambda: states[-1].simulation_time >= start_time + .2)
        p = states[-1].position
        assert np.linalg.norm(np.array([p.x, p.y, p.z]) - [.45, .25, .45]) > .05
    finally:
        clean_ros.node.destroy_subscription(subscription)


def test_ros_simulation_timeout(clean_ros):
    assert clean_ros.parameter('task_timeout', .02).successful
    response, _ = clean_ros.outcome('simulation_timeout', clean_ros.send([.45, .25, .45]))
    assert response.status == GoalStatus.STATUS_ABORTED
    assert not response.result.success
    assert response.result.elapsed_time >= .02
    assert 'timeout' in response.result.message


def test_ros_concurrent_goal_rejected(clean_ros):
    first = clean_ros.send([.45, .25, .45])
    assert first[0].accepted
    assert not clean_ros.send([.55, -.1, .55])[0].accepted
    response, _ = clean_ros.outcome('concurrent_first', first)
    assert response.status == GoalStatus.STATUS_SUCCEEDED
    assert response.result.final_error <= .005


def test_ros_reset_active_goal_and_stale_command(clean_ros):
    # Repeat acceptance/reset interleaving instead of relying on a long sleep.
    for iteration in range(3):
        old_generation = clean_ros.health().generation
        sent = clean_ros.send([.45, .25, .45])
        assert sent[0].accepted
        if iteration:
            clean_ros.wait(lambda: len(sent[1]) >= 2)
        reset = clean_ros.reset()
        assert reset.generation == old_generation + 1
        assert reset.simulation_time == 0.
        np.testing.assert_allclose(reset.joint_positions, HOME, atol=1e-12)
        response, _ = clean_ros.outcome('reset_active', sent)
        assert response.status == GoalStatus.STATUS_ABORTED
        assert 'Reset' in response.result.message
        assert not clean_ros.health().active_goal
        stale_client = clean_ros.node.create_client(Control, 'internal/control')
        clean_ros.wait(stale_client.service_is_ready)
        stale = Control.Request(generation=old_generation, sequence=100000)
        stale.target.x, stale.target.y, stale.target.z = [.5, .2, .5]
        assert not clean_ros.result(stale_client.call_async(stale)).accepted
        clean_ros.node.destroy_client(stale_client)
    response, _ = clean_ros.outcome('reach_after_reset', clean_ros.send([.5945, .03, .5945]))
    assert response.status == GoalStatus.STATUS_SUCCEEDED


def test_ros_health_and_parameters(clean_ros):
    health = clean_ros.health()
    assert health.healthy and health.ready
    assert not health.active_goal and not health.resetting
    assert 0 <= health.state_age_wall_seconds < 3
    assert clean_ros.parameter('target_tolerance', .001).successful
    for value in [0., -.01, float('nan'), float('inf'), -float('inf')]:
        rejected = clean_ros.parameter('target_tolerance', value)
        assert not rejected.successful
        assert 'finite and positive' in rejected.reason
    # Rejection must retain the last accepted value; this reach proves it is used.
    response, _ = clean_ros.outcome('updated_tolerance', clean_ros.send([.5945, .03, .5945]))
    assert response.status == GoalStatus.STATUS_SUCCEEDED
    assert response.result.final_error <= .001


def test_ros_parameter_update_during_goal(clean_ros):
    sent = clean_ros.send([.45, .25, .45])
    assert sent[0].accepted
    clean_ros.wait(lambda: len(sent[1]) >= 2)
    assert sent[1][-1].distance > .005
    assert clean_ros.parameter('target_tolerance', .001).successful
    response, _ = clean_ros.outcome('tolerance_updated_during_goal', sent)
    assert response.status == GoalStatus.STATUS_SUCCEEDED
    assert response.result.final_error <= .001

