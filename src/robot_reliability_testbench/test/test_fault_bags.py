import json
import os
from pathlib import Path
import uuid
import pytest

from reliability_testbench.fault_demo import run_demo


@pytest.fixture(scope='module')
def fault_demonstration(ros):
    root = Path(__file__).resolve().parents[3]
    reports = Path(os.environ.get('TESTBENCH_REPORT_DIR', root / 'reports'))
    bag = root / 'bags' / ('milestone_d_test_' + uuid.uuid4().hex[:10]) / 'faults'
    domain = int(os.environ.get('ROS_DOMAIN_ID', '0'))
    ros.reset()
    assert ros.parameter('task_timeout', 5.).successful
    assert ros.parameter('target_tolerance', .005).successful
    return run_demo(ros, bag, reports, 88 if domain != 88 else 89)


def test_fault_bag_demonstration_and_fresh_monitor_replay(fault_demonstration):
    result = fault_demonstration
    assert result['success'] and all(row['passed'] for row in result['scenarios'])
    assert {'STALE_OBSERVATIONS', 'NO_PROGRESS', 'OBSERVATIONS_RECOVERED', 'PROGRESS_RECOVERED'} <= {
        event['reason_code'] for event in result['offline']['diagnostics']}
    assert any(task['outcome'] == 'timeout' for task in result['offline']['tasks'])
    replay = result['replay']
    assert replay['success'] and replay['forbidden_published_topics'] == []
    assert replay['comparison'] == result['offline']['diagnostic_signature']
    assert replay['new_diagnostic_topic'] == '/replay/diagnostics'
    assert replay['new_diagnostics'][0]['monitor_session'] != replay['recorded_diagnostics'][0]['monitor_session']
    assert replay['replayed_topics'] == ['/testbench/observed/state', '/testbench/task_intent', '/clock']
    assert len(replay['new_diagnostics']) == len(replay['recorded_diagnostics'])
    assert result['isolation']['live_clock_publishers'] == 1
    from contextlib import closing
    import sqlite3
    database, = Path(result['offline']['bag']).glob('*.db3')
    with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as connection:
        assert connection.execute('PRAGMA journal_mode').fetchone() == ('wal',)


def test_fault_replay_long_recorder_discovery_prefix(fault_demonstration, ros, tmp_path):
    """A clock-only bag prefix must not become a false source-outage diagnosis."""
    import subprocess
    import rosbag2_py
    from rclpy.serialization import serialize_message
    from rosgraph_msgs.msg import Clock
    from reliability_testbench.fault_bags import D_TOPICS
    from reliability_testbench.bag_workflow import stop_process
    source = fault_demonstration['offline']['bag']
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=source), rosbag2_py.ConverterOptions('', ''))
    messages = []
    while reader.has_next():
        messages.append(reader.read_next())
    reader.close()
    bag = tmp_path / 'long_discovery_prefix'
    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(bag), storage_id='sqlite3'), rosbag2_py.ConverterOptions('', ''))
    for index, (topic, type_name) in enumerate(D_TOPICS.items(), 1):
        writer.create_topic(rosbag2_py.TopicMetadata(id=index, name=topic, type=type_name, serialization_format='cdr'))
    # Add a prefix longer than the unchanged 0.30 s live startup grace.
    writer.write('/clock', serialize_message(Clock()), min(m[2] for m in messages)-600_000_000)
    for topic, data, received in messages:
        writer.write(topic, data, received)
    writer.close()
    output = tmp_path / 'prefix.replay.json'
    with (tmp_path / 'prefix.launch.log').open('w') as log:
        process = subprocess.Popen(['ros2', 'launch', 'robot_reliability_testbench', 'fault_replay.launch.py',
            'bag:=' + str(bag), 'output:=' + str(output),
            f"live_domain:={fault_demonstration['live_domain']}",
            f"replay_domain:={fault_demonstration['replay_domain']}"],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            ros.wait(lambda: process.poll() is not None, timeout=30)
        finally:
            stop_process(process)
    assert output.exists()
    replay = json.loads(output.read_text())
    assert replay['success'], replay.get('error')
    assert len(replay['new_diagnostics']) == len(replay['recorded_diagnostics'])
    assert 'First captured affected observation' in replay['watchdog_arming']
