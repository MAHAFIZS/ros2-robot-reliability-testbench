import math
import time

import pytest
from geometry_msgs.msg import Point
from reliability_interfaces.msg import FaultConfiguration
from reliability_interfaces.srv import ConfigureFaults, Control
from reliability_testbench.fault_session import FaultSession


@pytest.fixture
def faults(clean_ros):
    session = FaultSession(clean_ros)
    session.ready()
    session.reset()
    try:
        yield session
    finally:
        session.reset()
        session.close()


def test_fault_healthy_motion_and_stationary(faults):
    subscriptions = dict(faults.node.get_subscriber_names_and_types_by_node('health_monitor', '/testbench'))
    assert set(subscriptions) == {'/testbench/observed/state', '/testbench/task_intent', '/clock'}
    controller_inputs = dict(faults.node.get_subscriber_names_and_types_by_node('task_server', '/testbench'))
    assert '/testbench/simulation_state' in controller_inputs
    assert not any('/observed/' in topic for topic in controller_inputs)
    index = len(faults.messages['diagnostic'])
    assert faults.finish(faults.send())['status'] == 4
    faults.wait_sim(.35)
    assert faults.messages['diagnostic'][index:] == []


def test_fault_drop_repeatability_and_recovery(faults):
    retained = []
    for _ in range(2):
        response = faults.configure(drop_every_n=3, seed=42)
        base = response.observation_sequence
        generation = faults.messages['observed'][-1][1].generation
        faults.client.wait(lambda: faults.messages['observed'][-1][1].sequence >= base+13)
        retained.append([message.sequence-base for _, message in faults.messages['observed']
                         if message.generation == generation and base < message.sequence <= base+12])
        faults.configure()
    assert retained[0] == retained[1] == [1, 2, 4, 5, 7, 8, 10, 11]
    faults.wait_sim(.04)
    index = len(faults.messages['diagnostic'])
    faults.wait_sim(.25)
    assert not any(m.reason_code == 'OBSERVATION_GAP' for _, m in faults.messages['diagnostic'][index:])


def test_fault_missing_latency_and_recovery(faults):
    index = len(faults.messages['diagnostic'])
    raw_count = len(faults.messages['raw'])
    started = time.monotonic()
    faults.configure(stop_publication=True)
    wall, event = faults.wait_diagnostic('STALE_OBSERVATIONS', index)
    assert wall-started <= .35
    assert len(faults.messages['raw']) > raw_count+3
    assert event.observation_age_steady_seconds >= .15
    faults.configure()
    faults.wait_diagnostic('OBSERVATIONS_RECOVERED', index)
    assert 'STALE_OBSERVATIONS' not in faults.status().active_reasons


def test_fault_freeze_during_motion_but_not_stationary(faults):
    index = len(faults.messages['diagnostic'])
    faults.configure(freeze=True)
    faults.wait_sim(.30)
    assert not any(m.reason_code == 'NO_PROGRESS' for _, m in faults.messages['diagnostic'][index:])
    frozen = faults.messages['observed'][-1][1]
    sent = faults.send()
    _, event = faults.wait_diagnostic('NO_PROGRESS', index, sent['goal_id'])
    latest = faults.messages['observed'][-1][1]
    assert latest.stamp != frozen.stamp and latest.sequence > frozen.sequence
    assert latest.position == frozen.position
    assert .20-1e-9 <= event.window_simulation_seconds <= .26
    assert event.observation_age_steady_seconds < .15
    raw = faults.messages['raw'][-1][1].position
    assert math.dist([raw.x, raw.y, raw.z], [latest.position.x, latest.position.y, latest.position.z]) > .01
    faults.configure()
    faults.wait_diagnostic('PROGRESS_RECOVERED', index, sent['goal_id'])
    assert faults.finish(sent)['status'] == 4  # Raw feedback controller, not affected-state robustness.


@pytest.mark.parametrize('combined', [False, True])
def test_fault_command_delay_and_drop_combination(faults, combined):
    index = len(faults.messages['diagnostic'])
    faults.configure(command_delay_seconds=.50, drop_every_n=3 if combined else 0)
    sent = faults.send()
    faults.wait_diagnostic('NO_PROGRESS', index, sent['goal_id'])
    faults.wait_diagnostic('PROGRESS_RECOVERED', index, sent['goal_id'])
    result = faults.finish(sent)
    assert result['status'] == 4
    applied = [m for _, m in faults.messages['command'] if m.goal_id == sent['goal_id'] and m.event == 'APPLIED'][-1]
    assert .50-1e-9 <= applied.applied_simulation_time-applied.enqueued_simulation_time <= .58
    if combined:
        assert any(m.reason_code == 'OBSERVATION_GAP' for _, m in faults.messages['diagnostic'][index:])


@pytest.mark.parametrize('fields', [dict(command_delay_seconds=-.1), dict(command_delay_seconds=2.1),
    dict(command_delay_seconds=float('nan')), dict(command_delay_seconds=float('inf')),
    dict(drop_every_n=1001), dict(queue_capacity=0), dict(queue_capacity=65)])
def test_fault_invalid_configuration_rejected(faults, fields):
    response = faults.client.result(faults.config.call_async(
        ConfigureFaults.Request(configuration=FaultConfiguration(**fields))))
    assert not response.accepted and response.message
    assert not response.configuration.freeze and response.configuration.command_delay_seconds == 0.


@pytest.mark.parametrize('termination', ['cancel', 'timeout', 'reset'])
def test_fault_pending_commands_never_execute_after_termination(faults, termination):
    faults.configure(command_delay_seconds=1., freeze=termination == 'reset',
                     drop_every_n=3 if termination == 'reset' else 0)
    if termination == 'timeout':
        assert faults.client.parameter('task_timeout', .15).successful
    sent = faults.send()
    faults.client.wait(lambda: any(m.goal_id == sent['goal_id'] and m.event == 'QUEUED'
                                  for _, m in faults.messages['command']))
    if termination == 'cancel':
        assert faults.client.result(sent['handle'].cancel_goal_async()).goals_canceling
    elif termination == 'reset':
        faults.reset()
    result = faults.finish(sent)
    assert result['status'] == (5 if termination == 'cancel' else 6)
    assert not result['success']
    faults.wait_sim(1.20)
    events = [m for _, m in faults.messages['command'] if m.goal_id == sent['goal_id'] and m.operation == 0]
    assert any(m.event == 'PURGED' for m in events)
    assert not any(m.event in ('FORWARDED', 'APPLIED') for m in events)
    if termination == 'reset':
        reset = [m for _, m in faults.messages['fault'] if m.event == 'RESET'][-1]
        assert not reset.configuration.freeze and reset.configuration.drop_every_n == 0
        assert reset.configuration.command_delay_seconds == 0.
        assert not faults.status().active_reasons


def test_fault_queue_fifo_overflow_and_disable_purge(faults):
    faults.configure(command_delay_seconds=.4, queue_capacity=2)
    client = faults.node.create_client(Control, '/testbench/boundary/control')
    faults.client.wait(client.service_is_ready)
    generation = faults.messages['raw'][-1][1].generation
    requests = [Control.Request(generation=generation, sequence=10000+i, goal_id='fifo',
                target=Point(x=.50, y=.10, z=.55)) for i in range(3)]
    futures = [client.call_async(request) for request in requests]
    assert not faults.client.result(futures[2]).accepted
    assert faults.client.result(futures[0]).accepted and faults.client.result(futures[1]).accepted
    faults.client.wait(lambda: len([m for _, m in faults.messages['command']
        if m.goal_id == 'fifo' and m.event == 'FORWARDED']) == 2)
    events = [m.sequence for _, m in faults.messages['command'] if m.goal_id == 'fifo' and m.event == 'FORWARDED']
    assert events == [10000, 10001]
    faults.configure(command_delay_seconds=1.)
    request = Control.Request(generation=generation, sequence=10003, goal_id='disable',
                              target=Point(x=.45, y=.2, z=.5))
    pending = client.call_async(request)
    faults.client.wait(lambda: any(m.goal_id == 'disable' and m.event == 'QUEUED' for _, m in faults.messages['command']))
    faults.configure()
    assert not faults.client.result(pending).accepted
    faults.wait_sim(1.1)
    assert not any(m.goal_id == 'disable' and m.event == 'FORWARDED' for _, m in faults.messages['command'])
    faults.node.destroy_client(client)
