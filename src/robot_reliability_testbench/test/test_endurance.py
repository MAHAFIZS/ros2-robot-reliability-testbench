"""Acceptance/report regression tests use adverse data, not simulator implementation details."""
import json
import math
import xml.etree.ElementTree as ET

import pytest

from reliability_testbench.endurance import acceptance, configuration, targets, write_reports


def line(process):
    import select
    assert select.select([process.stdout], [], [], 3)[0], 'Child readiness timeout'
    return process.stdout.readline().strip()


def healthy():
    return dict(configuration=configuration(min_tasks=1), measurement_wall_seconds=18.,
        tasks=[dict(success=True, status=4, final_error_metres=.0049, wall_seconds=.5)],
        observations=dict(count=900, missing_sequences=0, max_receive_interval_seconds=.021),
        diagnostics={}, fault_events=[], resources=[dict(samples=18, peak_rss_mib=100.,
            command=['/test/' + name for name in ('simulator', 'task_server', 'fault_boundary', 'health_monitor')])], failures=[])


def test_endurance_seeded_targets_repeat_and_do_not_stall():
    a, b, c = targets(7), targets(7), targets(8)
    sequence = [next(a) for _ in range(30)]
    assert sequence == [next(b) for _ in range(30)]
    assert sequence != [next(c) for _ in range(30)]
    assert all(x != y for x, y in zip(sequence, sequence[1:]))


@pytest.mark.parametrize('key,value', [('duration_seconds', math.nan), ('max_final_error', 0),
    ('duration_seconds', 5.), ('max_observation_gap_seconds', math.inf), ('min_tasks', 0)])
def test_endurance_rejects_invalid_configuration(key, value):
    with pytest.raises(ValueError):
        configuration(**{key: value})


@pytest.mark.parametrize('change,criterion', [
    (lambda r: r['tasks'][0].update(final_error_metres=.0051), 'final_position_error'),
    (lambda r: r['tasks'][0].update(final_error_metres=math.nan), 'final_position_error'),
    (lambda r: r['tasks'][0].update(success=False, status=6), 'all_tasks_succeeded'),
    (lambda r: r['observations'].update(missing_sequences=1), 'continuous_observations'),
    (lambda r: r['observations'].update(max_receive_interval_seconds=.2), 'continuous_observations'),
    (lambda r: r['diagnostics'].update(NO_PROGRESS=1), 'no_unexpected_diagnostics'),
    (lambda r: r.update(measurement_wall_seconds=17.), 'completed_window'),
    (lambda r: r.update(resources=[]), 'resources_collected'),
    (lambda r: r['resources'][0].update(peak_rss_mib=513.), 'per_process_rss_bound'),
    (lambda r: r['failures'].append('child exited'), 'no_infrastructure_failure')])
def test_endurance_acceptance_detects_regressions(change, criterion):
    report = healthy()
    assert all(c['passed'] for c in acceptance(report))
    change(report)
    assert not next(c for c in acceptance(report) if c['name'] == criterion)['passed']


def test_endurance_failure_reports_agree_and_escape_html(tmp_path):
    report = healthy()
    report['failures'] = ['<script>alert("failure")</script>']
    assert write_reports(report, tmp_path) == 1
    assert json.loads((tmp_path / 'endurance.json').read_text())['success'] is False
    xml = ET.parse(tmp_path / 'endurance.junit.xml').getroot()
    assert int(xml.attrib['failures']) == 1
    text = (tmp_path / 'endurance.html').read_text()
    assert '<script>' not in text and '&lt;script&gt;' in text
    assert write_reports(healthy(), tmp_path) == 0


def test_endurance_long_profile_is_thirty_minutes():
    assert configuration('local')['duration_seconds'] == 1800.
    assert configuration('local')['max_final_error'] == .005


def test_endurance_cleanup_includes_separate_session_child():
    import subprocess
    import sys
    import psutil
    from reliability_testbench.endurance import Resources, shutdown
    code = ('import subprocess,sys,time; '
            'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(3600)"],start_new_session=True); '
            'print(p.pid,flush=True); time.sleep(3600)')
    process = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    try:
        child = psutil.Process(int(line(process)))
        sampler = Resources(process)
        sampler.sample()
        assert len(sampler.summary()) == 2
        shutdown(process)
        assert process.poll() is not None
        assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
    finally:
        if process.poll() is None:
            shutdown(process)


def test_endurance_detects_disappearing_process():
    import subprocess
    import sys
    from reliability_testbench.endurance import Resources, shutdown
    code = ('import subprocess,sys,time; '
            'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(3600)"]); '
            'print("ready",flush=True); sys.stdin.readline(); p.terminate(); p.wait(timeout=2); '
            'print("gone",flush=True); time.sleep(3600)')
    process = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    try:
        assert line(process) == 'ready'
        sampler = Resources(process)
        sampler.sample()
        process.stdin.write('terminate child\n')
        process.stdin.flush()
        assert line(process) == 'gone'
        with pytest.raises(RuntimeError, match='disappeared'):
            sampler.sample()
    finally:
        shutdown(process)
