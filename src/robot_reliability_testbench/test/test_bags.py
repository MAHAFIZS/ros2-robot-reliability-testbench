"""Real recorded ROS traffic, actual rosbag readers, and adversarial bag contents."""
import json
import os
from pathlib import Path

import pytest
import rosbag2_py
from rclpy.serialization import serialize_message
from rosidl_runtime_py.utilities import get_message

from reliability_testbench.bag_analysis import TOPICS, BagAnalysisError, analyze_bag
from reliability_testbench.bag_workflow import run_verification, launch_replay
from reliability_testbench.replay import validate_domains


@pytest.fixture(scope='module')
def recorded(ros):
    # Session uses the same live launch as the original tests. Replay must remain isolated.
    live_domain = int(os.environ.get('ROS_DOMAIN_ID', '0'))
    replay_domain = 88 if live_domain != 88 else 89
    root = Path(__file__).resolve().parents[3]
    reports = Path(os.environ.get('TESTBENCH_REPORT_DIR', root / 'reports'))
    import uuid
    bag_root = root / 'bags' / ('milestone_c_test_' + uuid.uuid4().hex[:10])
    ros.reset()
    assert ros.parameter('target_tolerance', .005).successful
    assert ros.parameter('task_timeout', 5.).successful
    return run_verification(ros, bag_root, reports, live_domain, replay_domain)


def test_bags_healthy_record_analysis_and_isolated_replay(recorded):
    capture = recorded['captures'][0]
    assert capture['recorder_ready_before_goals']
    assert capture['terminal_persistence_barrier']
    assert capture['recorder_returncode'] == 0
    assert len(capture['offline']['outcomes']) == 3
    assert all(o['outcome'] == 'succeeded' and o['final_error_metres'] <= .005
               and o['matching_state_snapshot'] for o in capture['offline']['outcomes'])
    assert all(c['error_delta_metres'] <= 1e-9 for c in capture['comparisons'])
    replay = capture['replay']
    assert replay['success'] and replay['subscribers_ready_before_resume']
    assert replay['live_domain'] != replay['replay_domain']
    assert replay['live_domain_isolation_check']['graph_samples'] > 2
    assert not replay['live_domain_isolation_check']['replay_nodes_discovered']
    assert replay['live_domain_isolation_check']['live_health_after']
    assert replay['command_services_in_replay'] == []
    for topic in TOPICS:
        assert replay['topics'][topic]['count'] == capture['offline']['topics'][topic]['count']
        assert replay['topics'][topic]['sha256'] == capture['offline']['topics'][topic]['sha256']
    assert len(capture['offline']['task_events']) == 12  # Three reset/accept/target/complete lifecycles.
    assert capture['offline']['topics']['/clock']['message_stamp']['backwards_jumps'] >= 2
    assert capture['offline']['topics']['/clock']['bag_receive']['backwards_jumps'] == 0


def test_bags_cancellation_record_analysis_and_replay(recorded):
    capture = recorded['captures'][1]
    outcome, = capture['offline']['outcomes']
    assert outcome['outcome'] == 'canceled'
    assert outcome['elapsed_simulation_seconds'] > 0
    assert outcome['final_error_metres'] > .005
    assert capture['original_actions'][0]['status'] == 5
    assert capture['comparisons'][0]['error_delta_metres'] <= 1e-9
    assert capture['replay']['success']
    assert [e['event'] for e in capture['offline']['task_events']] == [
        'RESET', 'ACCEPTED', 'TARGET', 'CANCELED', 'COMPLETED']


def test_bags_concurrent_persistence_checks_use_wal(recorded):
    """Live persistence readers must not contend with native recorder writes."""
    from contextlib import closing
    import sqlite3
    for capture in recorded['captures']:
        database, = Path(capture['offline']['bag']).glob('*.db3')
        with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as connection:
            assert connection.execute('PRAGMA journal_mode').fetchone() == ('wal',)
            assert connection.execute('PRAGMA quick_check').fetchone() == ('ok',)


def write_bag(path, types, messages):
    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(path), storage_id='sqlite3'),
                rosbag2_py.ConverterOptions('', ''))
    for index, (topic, type_name) in enumerate(types.items(), 1):
        writer.create_topic(rosbag2_py.TopicMetadata(id=index, name=topic, type=type_name,
                                                   serialization_format='cdr'))
    for index, (topic, data) in enumerate(messages):
        writer.write(topic, data, 1_700_000_000_000_000_000 + index * 1000)
    writer.close()


def test_bags_missing_and_nonbag_paths(tmp_path):
    with pytest.raises(BagAnalysisError, match='finalized directory'):
        analyze_bag(tmp_path / 'missing')
    (tmp_path / 'metadata.yaml').write_text('not a bag')
    with pytest.raises(BagAnalysisError, match='Cannot read bag'):
        analyze_bag(tmp_path)


def test_bags_missing_required_topics(tmp_path):
    bag = tmp_path / 'missing_topics'
    write_bag(bag, {'/clock': TOPICS['/clock']}, [])
    with pytest.raises(BagAnalysisError, match='Missing required topics'):
        analyze_bag(bag)


def test_bags_empty_recording(tmp_path):
    bag = tmp_path / 'empty'
    write_bag(bag, TOPICS, [])
    with pytest.raises(BagAnalysisError, match='Empty required topics'):
        analyze_bag(bag)


def test_bags_wrong_topic_type(tmp_path):
    bag = tmp_path / 'wrong_type'
    types = dict(TOPICS)
    types['/testbench/raw/ee_pose'] = 'sensor_msgs/msg/JointState'
    write_bag(bag, types, [])
    with pytest.raises(BagAnalysisError, match='Wrong type'):
        analyze_bag(bag)


def test_bags_corrupt_cdr(tmp_path):
    bag = tmp_path / 'corrupt'
    write_bag(bag, TOPICS, [('/clock', b'not serialized CDR')])
    with pytest.raises(BagAnalysisError, match='Invalid message on /clock'):
        analyze_bag(bag)


def mutated_capture(recorded, tmp_path, mutate):
    source = recorded['captures'][0]['bag']
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=source), rosbag2_py.ConverterOptions('', ''))
    messages = []
    while reader.has_next():
        topic, data, _ = reader.read_next()
        if topic == '/testbench/task_events':
            from rclpy.serialization import deserialize_message
            event = deserialize_message(data, get_message(TOPICS[topic]))
            event = mutate(event)
            if event is None:
                continue
            data = serialize_message(event)
        messages.append((topic, data))
    reader.close()
    bag = tmp_path / 'mutated'
    write_bag(bag, TOPICS, messages)
    return bag


def test_bags_detect_missing_task_event(recorded, tmp_path):
    bag = mutated_capture(recorded, tmp_path, lambda e: None if e.event == 'TARGET' else e)
    with pytest.raises(BagAnalysisError, match='sequence gap'):
        analyze_bag(bag)


def test_bags_detect_inconsistent_error(recorded, tmp_path):
    def mutate(event):
        if event.event == 'COMPLETED':
            event.final_error += .01
        return event
    with pytest.raises(BagAnalysisError, match='error disagrees'):
        analyze_bag(mutated_capture(recorded, tmp_path, mutate))


def test_bags_detect_unfinished_goals(recorded, tmp_path):
    bag = mutated_capture(recorded, tmp_path, lambda e: None if e.event == 'COMPLETED' else e)
    with pytest.raises(BagAnalysisError, match='sequence gap|unfinished goal'):
        analyze_bag(bag)


def test_bags_filter_extra_command_topic(recorded, ros, tmp_path):
    source = recorded['captures'][0]['bag']
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=source), rosbag2_py.ConverterOptions('', ''))
    messages = []
    while reader.has_next():
        topic, data, _ = reader.read_next()
        messages.append((topic, data))
    reader.close()
    types = dict(TOPICS, **{'/testbench/commands': 'geometry_msgs/msg/Point'})
    from geometry_msgs.msg import Point
    messages.append(('/testbench/commands', serialize_message(Point(x=1., y=2., z=3.))))
    bag = tmp_path / 'extra_command'
    write_bag(bag, types, messages)
    offline = analyze_bag(bag)
    assert offline['ignored_topics'] == ['/testbench/commands']
    replay = launch_replay(ros, dict(scenario='filtered', bag=str(bag), offline=offline),
                           tmp_path, recorded['live_domain'], recorded['replay_domain'])
    assert replay['success']
    assert replay['excluded_bag_topics'] == ['/testbench/commands']
    assert replay['unexpected_testbench_topics'] == []


def test_bags_replay_launch_rejects_live_domain(tmp_path):
    import subprocess
    process = subprocess.run(['ros2', 'launch', 'robot_reliability_testbench', 'replay.launch.py',
        'bag:=not-opened', 'live_domain:=87', 'replay_domain:=87', 'output:=' + str(tmp_path / 'no.json')],
        capture_output=True, text=True, timeout=10)
    assert process.returncode != 0
    assert 'different from the live domain' in process.stdout + process.stderr
    assert not (tmp_path / 'no.json').exists()


def test_bags_timeout_and_active_reset_event_contract(clean_ros):
    from reliability_interfaces.msg import TaskEvent
    from rclpy.qos import QoSProfile
    events = []
    subscription = clean_ros.node.create_subscription(TaskEvent, 'task_events', events.append,
                                                       QoSProfile(depth=1000))
    try:
        clean_ros.wait(lambda: clean_ros.node.count_publishers('/testbench/task_events') == 1)
        assert clean_ros.parameter('task_timeout', .02).successful
        sent = clean_ros.send([.45, .25, .45])
        response = clean_ros.result(sent[0].get_result_async())
        assert response.status == 6
        goal_id = bytes(sent[0].goal_id.uuid).hex()
        clean_ros.wait(lambda: any(e.goal_id == goal_id and e.event == 'COMPLETED' for e in events))
        goal_events = [e for e in events if e.goal_id == goal_id]
        assert [e.event for e in goal_events] == ['ACCEPTED', 'TARGET', 'TIMEOUT', 'COMPLETED']
        assert goal_events[-1].outcome == 'timeout'
        assert abs(goal_events[-1].final_error-response.result.final_error) <= 1e-9
        assert clean_ros.parameter('task_timeout', 5.).successful
        sent = clean_ros.send([.45, .25, .45])
        clean_ros.wait(lambda: len(sent[1]) >= 2)
        reset = clean_ros.reset()
        goal_id = bytes(sent[0].goal_id.uuid).hex()
        response = clean_ros.result(sent[0].get_result_async())
        assert response.status == 6
        clean_ros.wait(lambda: any(e.goal_id == goal_id and e.event == 'RESET' for e in events))
        goal_events = [e for e in events if e.goal_id == goal_id]
        assert [e.event for e in goal_events] == ['ACCEPTED', 'TARGET', 'ABORTED', 'COMPLETED', 'RESET']
        assert goal_events[-2].outcome == 'reset'
        assert abs(goal_events[-2].final_error-response.result.final_error) <= 1e-9
        assert goal_events[-1].generation == reset.generation
        assert goal_events[-1].stamp.sec == 0 and goal_events[-1].stamp.nanosec == 0
        assert not goal_events[-1].has_position
    finally:
        clean_ros.node.destroy_subscription(subscription)


@pytest.mark.parametrize('live,replay', [(87, 87), (-1, 88), (87, 233)])
def test_bags_reject_unsafe_domains(live, replay):
    with pytest.raises(ValueError, match='domain|Domain'):
        validate_domains(live, replay)
