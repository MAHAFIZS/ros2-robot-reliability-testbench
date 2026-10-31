"""Bounded healthy workload; acceptance is fixed before launching any process."""
import argparse
import os
import datetime
import html
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import random
import signal
import subprocess
import time
import xml.etree.ElementTree as ET

PROFILES = {'short': dict(duration_seconds=18., min_tasks=10),
            'local': dict(duration_seconds=1800., min_tasks=1000)}
TARGETS = ((.5945, .03, .5945), (.50, -.08, .55), (.55, .10, .65))


def targets(seed):
    rng = random.Random(seed)
    previous = None
    while True:
        target = rng.choice([t for t in TARGETS if t != previous])
        previous = target
        yield target


def configuration(profile='short', **overrides):
    result = dict(profile=profile, seed=7, action_wall_timeout=6.,
        resource_sampling=True, timing_instrumentation=False,
        max_final_error=.005, max_observation_gap_seconds=.15,
        max_rss_mib=512., expected_injected_faults=False, **PROFILES[profile])
    result.update({key: value for key, value in overrides.items() if value is not None})
    for key in ('duration_seconds', 'action_wall_timeout', 'max_final_error',
                'max_observation_gap_seconds', 'max_rss_mib'):
        if not math.isfinite(result[key]) or result[key] <= 0:
            raise ValueError(key + ' must be finite and positive')
    if result['duration_seconds'] <= result['action_wall_timeout']:
        raise ValueError('duration must exceed the bounded action wait')
    if result['min_tasks'] < 1:
        raise ValueError('min_tasks must be positive')
    return result


def acceptance(report):
    c, tasks, obs = report['configuration'], report['tasks'], report['observations']
    def check(name, passed, observed, limit):
        return dict(name=name, passed=bool(passed), observed=observed, required=limit)
    errors = [t['final_error_metres'] for t in tasks]
    valid_errors = all(math.isfinite(e) and 0 <= e <= c['max_final_error'] for e in errors)
    resources = report['resources']
    return [check('completed_window', report['measurement_wall_seconds'] >= c['duration_seconds'],
                  report['measurement_wall_seconds'], c['duration_seconds']),
        check('minimum_tasks', len(tasks) >= c['min_tasks'], len(tasks), c['min_tasks']),
        check('all_tasks_succeeded', bool(tasks) and all(t['success'] and t['status'] == 4 for t in tasks),
              sum(t['success'] and t['status'] == 4 for t in tasks), len(tasks)),
        check('final_position_error', bool(tasks) and valid_errors, max(errors, default=None), c['max_final_error']),
        check('bounded_task_wall_time', all(t['wall_seconds'] <= c['action_wall_timeout'] for t in tasks),
              max((t['wall_seconds'] for t in tasks), default=None), c['action_wall_timeout']),
        check('continuous_observations', obs['count'] > 0 and obs['missing_sequences'] == 0 and
              obs['max_receive_interval_seconds'] <= c['max_observation_gap_seconds'], obs,
              dict(min_count=1, missing_sequences=0, max_interval=c['max_observation_gap_seconds'])),
        check('no_unexpected_diagnostics', not report['diagnostics'], report['diagnostics'], []),
        check('no_injected_faults', not report['fault_events'], report['fault_events'], []),
        check('resources_collected', bool(resources) and all(r['samples'] >= 2 for r in resources), len(resources), 'all tracked processes >=2 samples'),
        check('all_nodes_measured', all(any(any('/' + node == part[-len(node)-1:] for part in r.get('command', []))
              for r in resources) for node in ('simulator', 'task_server', 'fault_boundary', 'health_monitor')),
              [r.get('command', []) for r in resources], 'simulator, task_server, fault_boundary, health_monitor'),
        check('per_process_rss_bound', bool(resources) and all(r['peak_rss_mib'] <= c['max_rss_mib'] for r in resources),
              max((r['peak_rss_mib'] for r in resources), default=None), c['max_rss_mib']),
        check('no_infrastructure_failure', not report['failures'], report['failures'], [])]


def write_reports(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    report['criteria'] = acceptance(report)
    report['success'] = all(c['passed'] for c in report['criteria'])
    (directory / 'endurance.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    suite = ET.Element('testsuite', name='healthy_endurance', tests=str(len(report['criteria'])),
                       failures=str(sum(not c['passed'] for c in report['criteria'])))
    for criterion in report['criteria']:
        case = ET.SubElement(suite, 'testcase', name=criterion['name'], classname='endurance.acceptance')
        if not criterion['passed']:
            ET.SubElement(case, 'failure', message='Acceptance criterion failed').text = json.dumps(criterion)
    ET.ElementTree(suite).write(directory / 'endurance.junit.xml', encoding='utf-8', xml_declaration=True)
    rows = ''.join('<tr><td>' + html.escape(c['name']) + '</td><td>' +
        ('PASS' if c['passed'] else 'FAIL') + '</td><td><pre>' +
        html.escape(json.dumps(c['observed'], indent=2)) + '</pre></td><td><pre>' +
        html.escape(json.dumps(c['required'])) + '</pre></td></tr>' for c in report['criteria'])
    (directory / 'endurance.html').write_text('<!doctype html><meta charset="utf-8"><title>Robot endurance</title>'
        '<style>body{font:16px sans-serif;margin:2em}td,th{border:1px solid #aaa;padding:.5em}pre{white-space:pre-wrap}</style>'
        '<h1>Healthy endurance: ' + ('PASS' if report['success'] else 'FAIL') + '</h1>'
        '<table><tr><th>Criterion</th><th>Result</th><th>Observed</th><th>Required before run</th></tr>' + rows +
        '</table><h2>Measurements, provenance, failures and limitations</h2><pre>' +
        html.escape(json.dumps(report, indent=2)) + '</pre>')
    return 0 if report['success'] else 1


def provenance():
    def git(*args):
        p = subprocess.run(['git', *args], capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else None
    revision = os.environ.get('TESTBENCH_GIT_REVISION') or git('rev-parse', '--verify', 'HEAD')
    dirty = os.environ.get('TESTBENCH_GIT_DIRTY')
    status = git('status', '--porcelain') if dirty is None else None
    versions = {}
    for name in ('mujoco', 'numpy', 'pytest', 'psutil', 'rclpy', 'rosbag2_py', 'colcon-core'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = 'not installed'
    return dict(git_revision=None if revision in (None, 'unborn', 'unknown') else revision,
        git_revision_state=revision or 'unborn_or_unavailable',
        dirty_worktree=(dirty == 'true' if dirty in ('true', 'false') else (bool(status) if status is not None else None)),
        source_sha256=os.environ.get('TESTBENCH_SOURCE_SHA256'), python=platform.python_version(),
        platform=platform.platform(), dependencies=versions, ros_distro=os.environ.get('ROS_DISTRO'))


class Resources:
    """Aggregate samples online; memory use does not scale with run duration."""
    def __init__(self, process):
        import psutil
        self.root = psutil.Process(process.pid)
        self.records = {}

    def sample(self):
        import psutil
        now = time.monotonic()
        seen = set()
        for process in [self.root] + self.root.children(recursive=True):
            try:
                key = str(process.pid) + ':' + str(process.create_time())
                seen.add(key)
                rss = process.memory_info().rss / 1024 ** 2
                cpu = sum(process.cpu_times()[:2])
                if key not in self.records:
                    self.records[key] = dict(pid=process.pid, command=process.cmdline(), samples=0,
                        first_rss_mib=rss, last_rss_mib=rss, peak_rss_mib=rss,
                        mean_cpu_percent=0., peak_cpu_percent=0., first_time=now,
                        previous_time=now, previous_cpu=cpu, first_cpu=cpu, cpu_intervals=0)
                r = self.records[key]
                if now > r['previous_time']:
                    value = max(0., (cpu - r['previous_cpu']) / (now - r['previous_time']) * 100.)
                    r['cpu_intervals'] += 1
                    r['mean_cpu_percent'] += (value - r['mean_cpu_percent']) / r['cpu_intervals']
                    r['peak_cpu_percent'] = max(r['peak_cpu_percent'], value)
                r.update(samples=r['samples'] + 1, last_rss_mib=rss,
                         peak_rss_mib=max(rss, r['peak_rss_mib']), previous_cpu=cpu, previous_time=now)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        missing = set(self.records) - seen
        if missing:
            raise RuntimeError('Tracked launch processes disappeared during measurement: ' + ','.join(sorted(missing)))

    def summary(self):
        result = []
        for r in self.records.values():
            entry = {k: v for k, v in r.items() if k not in ('previous_cpu', 'previous_time', 'first_time', 'first_cpu', 'cpu_intervals')}
            elapsed = r['previous_time'] - r['first_time']
            entry['mean_cpu_percent'] = 100. * (r['previous_cpu'] - r['first_cpu']) / elapsed if elapsed else 0.
            entry['sampled_wall_seconds'] = elapsed
            entry['rss_endpoint_change_mib'] = r['last_rss_mib'] - r['first_rss_mib']
            entry['rss_endpoint_trend_mib_per_minute'] = entry['rss_endpoint_change_mib'] * 60 / elapsed if elapsed else None
            result.append(entry)
        return result


def shutdown(process):
    """Only terminate our owned launch tree, including orphan-prone descendants."""
    import psutil
    try:
        owned = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        owned = []
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    alive = [p for p in owned if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]
    for p in alive:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=2)
    for p in alive:
        p.kill()
    if process.poll() is None:
        process.kill()
    process.wait(timeout=3)
    if alive:
        raise RuntimeError('Owned processes required forced termination')


def run(config, directory):
    import rclpy
    from rclpy.signals import SignalHandlerOptions
    from reliability_interfaces.msg import ObservedState, DiagnosticEvent, FaultEvent
    from reliability_interfaces.srv import MonitorStatus, Reset
    from reliability_interfaces.action import Reach
    from ament_index_python.packages import get_package_share_directory
    import yaml
    from .bag_workflow import LiveClient
    from .timing_trace import Trace
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    trace_directory = directory.resolve() / 'timing'
    timing = Trace(trace_directory, 'runner') if config.get('timing_instrumentation') else None
    report = dict(configuration=config, acceptance_declared_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        provenance=provenance(), tasks=[], observations=dict(count=0, missing_sequences=0,
        max_receive_interval_seconds=0., max_simulation_interval_seconds=0.), diagnostics={}, fault_events=[],
        resources=[], failures=[], diagnostic_examples=[], tasks_attempted=0,
        robot_configuration=yaml.safe_load((Path(get_package_share_directory('robot_reliability_testbench')) / 'config/normal.yaml').read_text()),
        measurement_wall_seconds=0., simulation_duration_seconds=0.,
        limitations=['Healthy raw-state controller workload; injected faults are tested separately.',
          'Resources cover ros2 launch and its descendant processes, excluding runner, Docker daemon and kernel.',
          'CPU percent is process CPU time / steady wall interval; multithreaded values may exceed 100%.',
          'RSS endpoint trends are descriptive; short runs cannot establish absence of memory leaks.',
          'Measurement window excludes startup/warmup/shutdown; final six seconds reserve bounded action completion.',
          'Receive intervals use steady time; task durations and observation stamps use simulator time.'])
    (directory / 'acceptance.before_run.json').write_text(json.dumps(config, indent=2) + '\n')
    total_start = time.monotonic()
    process = client = sampler = None
    initialized = False
    measuring = False
    latest = None
    previous = None
    next_sample = 0.
    clock_start = None
    measurement_start = None
    def observe(message):
        entry_ns = time.monotonic_ns()
        nonlocal latest, previous
        latest = message
        if timing:
            timing.observe(message, entry_ns)
        if not measuring:
            return
        now = entry_ns / 1e9
        obs = report['observations']
        obs['count'] += 1
        if previous:
            old, received = previous
            obs['max_receive_interval_seconds'] = max(obs['max_receive_interval_seconds'], now - received)
            obs['max_simulation_interval_seconds'] = max(obs['max_simulation_interval_seconds'], message.simulation_time - old.simulation_time)
            if old.generation == message.generation:
                obs['missing_sequences'] += max(0, message.sequence - old.sequence - 1)
        previous = message, now
    def diagnostic(message):
        if measuring:
            counts = report['diagnostics']
            counts[message.reason_code] = counts.get(message.reason_code, 0) + 1
            if len(report['diagnostic_examples']) < 20:
                report['diagnostic_examples'].append(dict(reason_code=message.reason_code, active=message.active,
                    evidence=message.evidence, goal_id=message.goal_id, observation_sequence=message.observation_sequence,
                    simulation_stamp_seconds=message.stamp.sec + message.stamp.nanosec / 1e9))
    def fault(message):
        if measuring and len(report['fault_events']) < 100:
            report['fault_events'].append(str(message))
    def spin_until(predicate, timeout):
        nonlocal next_sample
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Launch process exited unexpectedly')
            spin_start_ns = time.monotonic_ns() if timing else 0
            rclpy.spin_once(client.node, timeout_sec=.01)
            if timing:
                timing.emit('spin', start_ns=spin_start_ns, end_ns=time.monotonic_ns())
            if sampler and time.monotonic() >= next_sample:
                sample_start_ns = time.monotonic_ns() if timing else 0
                sampler.sample()
                if timing:
                    timing.emit('resource_sample', start_ns=sample_start_ns, end_ns=time.monotonic_ns())
                next_sample = time.monotonic() + 1.
            if predicate():
                return
        raise RuntimeError('Endurance bounded wait expired')
    def result(future, timeout=6.):
        spin_until(future.done, timeout)
        return future.result()
    try:
        with (directory / 'launch.log').open('w') as log:
            launch_env = dict(os.environ)
            if timing:
                launch_env['TESTBENCH_TIMING_DIR'] = str(trace_directory)
            else:
                launch_env.pop('TESTBENCH_TIMING_DIR', None)
            process = subprocess.Popen(['ros2', 'launch', 'robot_reliability_testbench', 'normal.launch.py'],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=launch_env)
            rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
            initialized = True
            client = LiveClient()
            client.node.create_subscription(ObservedState, '/testbench/observed/state', observe, 1000)
            client.node.create_subscription(DiagnosticEvent, '/testbench/diagnostics', diagnostic, 1000)
            client.node.create_subscription(FaultEvent, '/testbench/fault_events', fault, 1000)
            monitor = client.node.create_client(MonitorStatus, '/testbench/observation_health')
            spin_until(lambda: client.health_client.service_is_ready() and client.reset_client.service_is_ready()
                and client.action.server_is_ready() and monitor.service_is_ready() and latest is not None, 20)
            spin_until(lambda: result(client.health_client.call_async(__import__('reliability_interfaces.srv', fromlist=['Health']).Health.Request())).ready, 10)
            reset = result(client.reset_client.call_async(Reset.Request()))
            if not reset.success:
                raise RuntimeError('Startup reset failed')
            spin_until(lambda: latest is not None and latest.generation == reset.generation and latest.simulation_time >= .5, 5)
            status = result(monitor.call_async(MonitorStatus.Request()))
            if not status.ready or status.active_reasons:
                raise RuntimeError('Monitor unhealthy after warmup: ' + str(status.active_reasons))
            sampler = Resources(process) if config.get('resource_sampling', True) else None
            if sampler:
                sample_start_ns = time.monotonic_ns() if timing else 0
                sampler.sample()
                if timing:
                    timing.emit('resource_sample', start_ns=sample_start_ns, end_ns=time.monotonic_ns())
            measurement_start = time.monotonic()
            if timing:
                timing.emit('measurement_start', start_ns=int(measurement_start * 1e9))
            clock_start = latest.simulation_time
            previous = latest, measurement_start
            report['startup_wall_seconds'] = measurement_start - total_start
            measuring = True
            sequence = targets(config['seed'])
            deadline = measurement_start + config['duration_seconds']
            while time.monotonic() < deadline - config['action_wall_timeout']:
                target = next(sequence)
                goal = Reach.Goal()
                goal.target.x, goal.target.y, goal.target.z = target
                started = time.monotonic()
                report['tasks_attempted'] += 1
                handle = result(client.action.send_goal_async(goal), 2.)
                if not handle.accepted:
                    raise RuntimeError('Healthy endurance goal rejected')
                response = result(handle.get_result_async(), config['action_wall_timeout'] - (time.monotonic() - started))
                value = response.result
                report['tasks'].append(dict(target_metres=target, success=value.success, status=response.status,
                    final_error_metres=value.final_error, simulation_seconds=value.elapsed_time,
                    wall_seconds=time.monotonic() - started, message=value.message))
            spin_until(lambda: time.monotonic() >= deadline, max(0., deadline - time.monotonic()) + .1)
            report['measurement_wall_seconds'] = time.monotonic() - measurement_start
            if timing:
                timing.emit('measurement_end', end_ns=time.monotonic_ns())
                timing.trailing_gap(time.monotonic_ns())
            report['simulation_duration_seconds'] = latest.simulation_time - clock_start
            # Include the trailing receive gap so a stopped publisher cannot silently pass.
            if previous:
                report['observations']['max_receive_interval_seconds'] = max(
                    report['observations']['max_receive_interval_seconds'], time.monotonic() - previous[1])
            if sampler:
                sample_start_ns = time.monotonic_ns() if timing else 0
                sampler.sample()
                if timing:
                    timing.emit('resource_sample', start_ns=sample_start_ns, end_ns=time.monotonic_ns())
    except Exception as exc:
        report['failures'].append(type(exc).__name__ + ': ' + str(exc))
        if measurement_start is not None:
            report['measurement_wall_seconds'] = time.monotonic() - measurement_start
            report['simulation_duration_seconds'] = latest.simulation_time - clock_start
    finally:
        measuring = False
        if sampler:
            report['resources'] = sampler.summary()
        if client:
            client.node.destroy_node()
        if initialized:
            rclpy.shutdown()
        if process:
            try:
                shutdown(process)
            except Exception as exc:
                report['failures'].append('shutdown: ' + str(exc))
        if timing:
            try:
                timing.close()
                report['timing_directory'] = str(trace_directory)
            except Exception as exc:
                report['failures'].append('timing: ' + str(exc))
        report['experiment_kind'] = ('diagnostic_resource_sampling_disabled'
            if not config.get('resource_sampling', True) else 'healthy_with_resource_sampling')
        report['total_wall_seconds'] = time.monotonic() - total_start
        report['completed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return write_reports(report, directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, default='short')
    parser.add_argument('--output', default='reports/endurance')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--duration-seconds', type=float)
    parser.add_argument('--min-tasks', type=int)
    parser.add_argument('--max-final-error', type=float)
    parser.add_argument('--timing', action='store_true', help='Optional bounded process-local timing traces')
    parser.add_argument('--disable-resource-sampling', action='store_true',
                        help='Diagnostic only: full acceptance still reports missing-resource criteria as failed')
    args = parser.parse_args()
    config = configuration(args.profile, seed=args.seed, duration_seconds=args.duration_seconds,
                           min_tasks=args.min_tasks, max_final_error=args.max_final_error,
                           timing_instrumentation=args.timing, resource_sampling=not args.disable_resource_sampling)
    def interrupted(signum, frame):
        raise RuntimeError('Runner interrupted by signal ' + str(signum))
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    raise SystemExit(run(config, args.output))


if __name__ == '__main__':
    main()
