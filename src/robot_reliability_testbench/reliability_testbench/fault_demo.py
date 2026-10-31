"""Short measured D demonstration; no endurance, Docker or CI work."""
import argparse
import datetime
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import uuid

import rclpy
from rclpy.utilities import get_rmw_implementation_identifier

from .bag_workflow import LiveClient, stop_process
from .fault_session import FaultSession, demo_scenarios
from .fault_bags import FaultRecorder, analyze_fault_bag
from .replay import validate_domains


def run_demo(client, bag, reports, replay_domain=88):
    reports = Path(reports).resolve()
    reports.mkdir(parents=True, exist_ok=True)
    live_domain = int(os.environ.get('ROS_DOMAIN_ID', '0'))
    validate_domains(live_domain, replay_domain)
    session = FaultSession(client)
    progress = dict(milestone='D', success=False, phase='capture', bag=str(bag))
    (reports / 'milestone_d.json').write_text(json.dumps(progress, indent=2)+'\n')
    try:
        session.ready()
        session.reset()
        with FaultRecorder(client, bag, reports) as recorder:
            scenarios = demo_scenarios(session)
            session.wait_sim(.10)
            recorder.drain(session)
        offline = analyze_fault_bag(str(Path(bag).resolve()))
        (reports / 'milestone_d.analysis.json').write_text(json.dumps(offline, indent=2)+'\n')
        progress.update(phase='replay', scenarios=scenarios, offline=offline)
        (reports / 'milestone_d.json').write_text(json.dumps(progress, indent=2)+'\n')
        replay_file = reports / 'milestone_d.replay.json'
        if replay_file.exists():
            replay_file.unlink()
        live_samples = []
        with (reports / 'milestone_d.replay.launch.log').open('w') as log:
            process = subprocess.Popen(['ros2', 'launch', 'robot_reliability_testbench', 'fault_replay.launch.py',
                'bag:=' + str(Path(bag).resolve()), 'output:=' + str(replay_file),
                f'live_domain:={live_domain}', f'replay_domain:={replay_domain}'],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            def finished():
                names = client.node.get_node_names()
                if 'fault_replay_observer' in names or 'replay_health_monitor' in names or 'rosbag2_player' in names:
                    raise RuntimeError('Fresh replay node discovered in live domain')
                count = len(client.node.get_publishers_info_by_topic('/clock'))
                if count != 1:
                    raise RuntimeError('Live domain clock publisher count changed')
                live_samples.append(count)
                return process.poll() is not None
            try:
                client.wait(finished, timeout=max(30., offline['bag_receive_duration_seconds']*2+15))
            finally:
                stop_process(process)
        if process.returncode != 0 or not replay_file.exists():
            raise RuntimeError('Fresh-monitor replay launch failed')
        replay = json.loads(replay_file.read_text())
        if not replay.get('success'):
            raise RuntimeError('Fresh-monitor replay failed: ' + replay.get('error', 'unknown'))
        result = dict(milestone='D', success=True, scenarios=scenarios, offline=offline, replay=replay,
            executed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            live_domain=live_domain, replay_domain=replay_domain,
            isolation=dict(live_graph_samples=len(live_samples), replay_nodes_in_live=False,
                           live_clock_publishers=1, live_observation_alerts=session.status().active_reasons),
            environment=dict(python=platform.python_version(), platform=platform.platform(),
                mujoco=metadata.version('mujoco'), rosbag2_py=metadata.version('rosbag2-py'),
                rmw=get_rmw_implementation_identifier()),
            limitations=['Controller uses raw simulator state, not affected observations; no closed-loop sensor robustness claim',
                'NO_PROGRESS cannot distinguish freeze, blocked motion or delayed commands',
                'Diagnostic lifecycle order and observation-gap order compared separately; steady timing is not identical on replay',
                'Overload-driven queue expiry and arbitrary in-flight transport failure recovery are not exercised',
                'Fixed deterministic faults, seed metadata only; no physical hardware, Docker, CI or endurance validation'])
        suite_file = reports / 'milestone_d.tests.json'
        if suite_file.exists():
            result['suite'] = json.loads(suite_file.read_text())
        (reports / 'milestone_d.json').write_text(json.dumps(result, indent=2)+'\n')
        return result
    except Exception as exc:
        progress['error'] = str(exc)
        (reports / 'milestone_d.json').write_text(json.dumps(progress, indent=2)+'\n')
        raise
    finally:
        session.reset()
        session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bag-root', default='bags/milestone_d_' + uuid.uuid4().hex[:10])
    parser.add_argument('--reports', default='reports')
    parser.add_argument('--replay-domain', type=int, default=88)
    args = parser.parse_args()
    reports = Path(args.reports).resolve()
    reports.mkdir(parents=True, exist_ok=True)
    with (reports / 'milestone_d.live.launch.log').open('w') as log:
        process = subprocess.Popen(['ros2', 'launch', 'robot_reliability_testbench', 'normal.launch.py'],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        rclpy.init()
        client = LiveClient()
        try:
            result = run_demo(client, Path(args.bag_root) / 'faults', reports, args.replay_domain)
            print(json.dumps(dict(success=result['success'],
                scenarios=[dict(scenario=s['scenario'], passed=s['passed']) for s in result['scenarios']],
                bag=result['offline']['bag']), indent=2))
        finally:
            client.node.destroy_node()
            rclpy.shutdown()
            stop_process(process)


if __name__ == '__main__':
    main()
