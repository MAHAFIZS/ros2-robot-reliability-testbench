"""Virtual steady time exercises health rules without ROS or simulator internals."""
import pytest
from reliability_testbench.monitor_core import MonitorCore


def observation(sequence, time, x=0., generation=1):
    return dict(sequence=sequence, time=time, generation=generation, position=[x, 0., 0.], joints=[0.] * 7)


def intent(active=True):
    return dict(active=active, generation=1, goal_id='example', target=[1., 0., 0.], tolerance=.005)


def test_monitor_healthy_stationary_and_motion():
    events = []
    core = MonitorCore(events.append, 0.)
    core.task_intent(intent(False), 0.)
    for i in range(30):
        core.observe(observation(i+1, i*.02), i*.02)
        core.tick(i*.02)
    core.task_intent(intent(), .6)
    for i in range(30, 60):
        core.observe(observation(i+1, i*.02, x=(i-29)*.02), i*.02)
    assert events == []


def test_monitor_fresh_frozen_values_report_only_no_progress():
    events = []
    core = MonitorCore(events.append, 0.)
    core.task_intent(intent(), 0.)
    for i in range(20):
        core.observe(observation(i+1, i*.02), i*.02)
        core.tick(i*.02)
    assert [e['reason_code'] for e in events] == ['NO_PROGRESS']
    assert events[0]['window_simulation_seconds'] == pytest.approx(.20)
    assert 'cannot be distinguished' in events[0]['evidence']
    core.observe(observation(21, .4, .02), .4)
    assert events[-1]['reason_code'] == 'PROGRESS_RECOVERED'


def test_monitor_pause_uses_steady_watchdog_and_recovers():
    events = []
    core = MonitorCore(events.append, 0.)
    core.observe(observation(1, 0.), 0.)
    core.clock = 0.  # Paused simulation; steady time continues.
    core.tick(.16)
    assert events[-1]['reason_code'] == 'STALE_OBSERVATIONS'
    assert events[-1]['simulation_time'] == 0.
    core.observe(observation(2, 0.), .17)
    assert events[-1]['reason_code'] == 'OBSERVATIONS_RECOVERED'


def test_monitor_startup_grace_and_generation():
    events = []
    core = MonitorCore(events.append, 0.)
    core.tick(.29)
    assert events == []
    core.tick(.31)
    assert events[-1]['reason_code'] == 'STALE_OBSERVATIONS'
    core.observe(observation(100, .5), .32)
    core.observe(observation(1, 0., generation=2), .34)
    assert all(e['reason_code'] != 'OBSERVATION_GAP' for e in events)


@pytest.mark.parametrize('invalid_field', ['position', 'joint', 'time'])
def test_monitor_gap_and_invalid_values(invalid_field):
    events = []
    core = MonitorCore(events.append, 0.)
    core.observe(observation(1, 0.), 0.)
    core.observe(observation(4, .06), .06)
    assert events[-1]['reason_code'] == 'OBSERVATION_GAP' and events[-1]['missing_count'] == 2
    invalid = observation(5, .08)
    if invalid_field == 'position':
        invalid['position'][0] = float('nan')
    elif invalid_field == 'joint':
        invalid['joints'][0] = float('nan')
    else:
        invalid['time'] = float('nan')
    core.observe(invalid, .08)
    assert events[-1]['reason_code'] == 'INVALID_OBSERVATION'


def test_monitor_repeatability():
    runs = []
    for _ in range(3):
        events = []
        core = MonitorCore(events.append, 0.)
        core.task_intent(intent(), 0.)
        for i in range(30):
            if (i+1) % 3:
                core.observe(observation(i+1, i*.02), i*.02)
            core.tick(i*.02)
        runs.append(events)
    assert runs[0] == runs[1] == runs[2]
