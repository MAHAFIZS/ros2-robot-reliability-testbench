"""Offline rosbag2 reader. No ROS graph, action results or demo JSON required."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.convert import message_to_ordereddict
from rosidl_runtime_py.utilities import get_message

TOPICS = {
    '/testbench/raw/joint_states': 'sensor_msgs/msg/JointState',
    '/testbench/raw/ee_pose': 'geometry_msgs/msg/PoseStamped',
    '/testbench/simulation_state': 'reliability_interfaces/msg/SimulationState',
    '/testbench/task_events': 'reliability_interfaces/msg/TaskEvent',
    '/clock': 'rosgraph_msgs/msg/Clock',
}
ERROR_TOLERANCE = 1e-9


class BagAnalysisError(ValueError):
    """Missing, corrupt or incomplete observations; never silently pass a capture."""


def stamp_ns(stamp):
    if not 0 <= stamp.nanosec < 10**9:
        raise BagAnalysisError('Invalid message timestamp nanoseconds')
    return stamp.sec * 10**9 + stamp.nanosec


def message_stamp(message):
    if hasattr(message, 'header'):
        return stamp_ns(message.header.stamp)
    if hasattr(message, 'stamp'):
        return stamp_ns(message.stamp)
    return stamp_ns(message.clock)


def xyz(point):
    return [point.x, point.y, point.z]


def distance(a, b):
    return math.dist(a, b)


class TopicDigest:
    """Canonical message-content digest, insensitive to CDR padding bytes."""
    def __init__(self):
        self.count = 0
        self.digest = hashlib.sha256()

    def add(self, message):
        data = message_to_ordereddict(message)
        encoded = json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        self.digest.update(encoded + b'\n')
        self.count += 1

    def summary(self):
        return dict(count=self.count, sha256=self.digest.hexdigest())


def timing(values):
    intervals = [b - a for a, b in zip(values, values[1:])]
    return dict(first_ns=values[0], last_ns=values[-1], minimum_ns=min(values), maximum_ns=max(values),
        backwards_jumps=sum(x < 0 for x in intervals),
        intervals_ns=(dict(minimum=min(intervals), maximum=max(intervals),
                           mean=statistics.mean(intervals), median=statistics.median(intervals))
                      if intervals else None))


def analyze_bag(path):
    path = Path(path).resolve()
    if not path.is_dir() or not (path / 'metadata.yaml').is_file():
        raise BagAnalysisError(f'Invalid bag: expected a finalized directory with metadata.yaml: {path}')
    reader = rosbag2_py.SequentialReader()
    opened = False
    try:
        reader.open(rosbag2_py.StorageOptions(uri=str(path)), rosbag2_py.ConverterOptions('', ''))
        opened = True
        available = {topic.name: topic.type for topic in reader.get_all_topics_and_types()}
        missing = set(TOPICS) - available.keys()
        if missing:
            raise BagAnalysisError('Missing required topics: ' + ', '.join(sorted(missing)))
        for topic, expected in TOPICS.items():
            if available[topic] != expected:
                raise BagAnalysisError(f'Wrong type for {topic}: {available[topic]}, expected {expected}')
        types = {topic: get_message(type_name) for topic, type_name in TOPICS.items()}
        digests = {topic: TopicDigest() for topic in TOPICS}
        receive = {topic: [] for topic in TOPICS}
        stamps = {topic: [] for topic in TOPICS}
        events = []
        states = {}
        for_reader_count = 0
        while reader.has_next():
            topic, data, received = reader.read_next()
            for_reader_count += 1
            if topic not in TOPICS:
                continue
            try:
                message = deserialize_message(data, types[topic])
                stamp = message_stamp(message)
                digests[topic].add(message)  # Also rejects nonfinite numeric fields.
                if topic.endswith('/joint_states') and (len(message.position) != 7
                                                         or len(message.velocity) != 7):
                    raise BagAnalysisError('Expected seven joint positions and velocities')
                if topic.endswith('/simulation_state'):
                    if abs(stamp - round(message.simulation_time * 1e9)) > 1:
                        raise BagAnalysisError('SimulationState stamp disagrees with physics time')
                    states[(message.generation, stamp)] = xyz(message.position)
                if topic.endswith('/task_events'):
                    event = message_to_ordereddict(message)
                    event['bag_receive_ns'] = received
                    event['message_stamp_ns'] = stamp
                    events.append(event)
            except Exception as exc:
                raise BagAnalysisError(f'Invalid message on {topic}: {exc}') from exc
            receive[topic].append(received)
            stamps[topic].append(stamp)
        empty = [topic for topic in TOPICS if not receive[topic]]
        if empty:
            raise BagAnalysisError('Empty required topics: ' + ', '.join(empty))
        goals, last_sequences = {}, {}
        outcomes = []
        for event in events:
            session, sequence, goal = event['session_id'], event['sequence'], event['goal_id']
            if not session or not goal or sequence <= 0:
                raise BagAnalysisError('Task event requires session, goal identifier and positive sequence')
            if session in last_sequences and sequence != last_sequences[session] + 1:
                raise BagAnalysisError('Task-event sequence gap, duplicate or reordered event')
            last_sequences[session] = sequence
            key = (session, goal)
            kind = event['event']
            if kind == 'RESET':
                continue
            if kind == 'ACCEPTED':
                if key in goals:
                    raise BagAnalysisError('Duplicate goal acceptance')
                goals[key] = dict(accepted=event, target_seen=False, marker=None, completed=False)
                continue
            if key not in goals:
                raise BagAnalysisError(f'{kind} has no recorded goal acceptance (capture started too late)')
            lifecycle = goals[key]
            if lifecycle['completed']:
                raise BagAnalysisError('Event after goal completion')
            if kind == 'TARGET':
                if lifecycle['target_seen']:
                    raise BagAnalysisError('Duplicate target event')
                lifecycle['target_seen'] = True
            elif kind in ('CANCELED', 'TIMEOUT', 'ABORTED'):
                if lifecycle['marker'] is not None:
                    raise BagAnalysisError('Duplicate terminal marker')
                lifecycle['marker'] = kind
            elif kind == 'COMPLETED':
                outcome = event['outcome']
                expected_marker = {'succeeded': None, 'canceled': 'CANCELED', 'timeout': 'TIMEOUT',
                                   'reset': 'ABORTED', 'aborted': 'ABORTED'}
                if (not lifecycle['target_seen'] or outcome not in expected_marker
                        or lifecycle['marker'] != expected_marker[outcome] or not event['has_position']):
                    raise BagAnalysisError('Incomplete or inconsistent task lifecycle')
                target = list(event['target'].values())
                accepted_target = list(lifecycle['accepted']['target'].values())
                if target != accepted_target:
                    raise BagAnalysisError('Target changed within a goal')
                position = list(event['position'].values())
                error = distance(position, target)
                if abs(error - event['final_error']) > ERROR_TOLERANCE:
                    raise BagAnalysisError('Terminal error disagrees with target/position snapshot')
                if event['elapsed_simulation_seconds'] < 0 or event['elapsed_wall_seconds'] < 0:
                    raise BagAnalysisError('Negative task duration')
                if outcome == 'succeeded' and (event['tolerance'] <= 0 or error > event['tolerance']):
                    raise BagAnalysisError('Success outside recorded tolerance')
                state = states.get((event['generation'], event['message_stamp_ns']))
                matched = state is not None and distance(position, state) <= ERROR_TOLERANCE
                outcomes.append(dict(goal_id=goal, session_id=session, outcome=outcome,
                    target_metres=target, final_position_metres=position, final_error_metres=error,
                    event_final_error_metres=event['final_error'], matching_state_snapshot=matched,
                    elapsed_simulation_seconds=event['elapsed_simulation_seconds'],
                    elapsed_wall_seconds=event['elapsed_wall_seconds'],
                    bag_receive_duration_seconds=(event['bag_receive_ns'] - lifecycle['accepted']['bag_receive_ns']) / 1e9,
                    terminal_message_stamp_ns=event['message_stamp_ns'], generation=event['generation']))
                lifecycle['completed'] = True
            else:
                raise BagAnalysisError('Unknown task event: ' + kind)
        if not outcomes or any(not goal['completed'] for goal in goals.values()):
            raise BagAnalysisError('Recording has no completed tasks or contains an unfinished goal')
        all_receives = [value for values in receive.values() for value in values]
        return dict(bag=str(path), storage_id=reader.get_metadata().storage_identifier,
            topics={topic: dict(type=TOPICS[topic], **digests[topic].summary(),
                                bag_receive=timing(receive[topic]), message_stamp=timing(stamps[topic]))
                    for topic in TOPICS},
            bag_receive_duration_seconds=(max(all_receives) - min(all_receives)) / 1e9,
            task_events=events, outcomes=outcomes, total_stored_messages=for_reader_count,
            ignored_topics=sorted(set(available) - set(TOPICS)),
            numerical_error_tolerance_metres=ERROR_TOLERANCE,
            timing_notes='Bag receive ns use recorder system time. Message stamps are simulation time, '
                         'with backwards jumps at reset. Task simulation and monotonic wall durations '
                         'come from recorded events. Receive duration includes DDS transport/scheduling.')
    except BagAnalysisError:
        raise
    except Exception as exc:
        raise BagAnalysisError(f'Cannot read bag {path}: {exc}') from exc
    finally:
        if opened:
            reader.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bag')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = analyze_bag(args.bag)
    except BagAnalysisError as exc:
        parser.exit(2, f'Bag analysis failed: {exc}\n')
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(bag=result['bag'], counts={t: v['count'] for t, v in result['topics'].items()},
                          outcomes=result['outcomes']), indent=2))


if __name__ == '__main__':
    main()
