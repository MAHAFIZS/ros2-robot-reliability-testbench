"""Opt-in local CLOCK_MONOTONIC tracing; no ROS messages or control decisions."""
from collections import Counter, deque
import json
import os
from pathlib import Path
import queue
import threading
import time

THRESHOLD_NS = 150_000_000


def stamp_ns(message):
    return message.stamp.sec * 1_000_000_000 + message.stamp.nanosec


def clock_identity():
    return dict(implementation=time.get_clock_info('monotonic').implementation,
                resolution_seconds=time.get_clock_info('monotonic').resolution,
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                time_namespace=os.readlink('/proc/self/ns/time'))


class Trace:
    """Callbacks enqueue only. Writer owns encoding, file I/O and flushes."""
    def __init__(self, directory, role, capacity=4096, priority_capacity=1024,
                 max_records=200000, context=12):
        self.role = role
        self.path = Path(directory) / (role + '.jsonl')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.normal = queue.Queue(capacity)
        self.priority = queue.Queue(priority_capacity)
        self.max_records = max_records
        self.history = deque(maxlen=context)
        self.pending = deque(maxlen=context + 1)
        self.context = context
        self.last = None
        self.closed = threading.Event()
        self.counts = Counter()
        self.cost_buckets = Counter()
        self.cost_total_ns = self.cost_max_ns = 0
        self.error = None
        self.thread = threading.Thread(target=self._write, name='timing-writer', daemon=True)
        self.thread.start()
        self.emit('metadata', clock=clock_identity(), pid=os.getpid(), role=role,
                  capacity=capacity, priority_capacity=priority_capacity,
                  normal_record_limit=max_records, context_samples=context)

    @classmethod
    def from_environment(cls, role):
        directory = os.environ.get('TESTBENCH_TIMING_DIR')
        return cls(directory, role) if directory else None

    def _enqueue(self, event, priority=False):
        self.counts['submitted'] += 1
        try:
            (self.priority if priority else self.normal).put_nowait(event)
        except queue.Full:
            self.counts['dropped_priority' if priority else 'dropped_queue'] += 1

    def emit(self, kind, **values):
        started = time.monotonic_ns()
        self._enqueue(dict(kind=kind, time_ns=started, **values))
        self._cost(started)

    def _cost(self, started):
        cost = time.monotonic_ns() - started
        self.counts['instrumentation_calls'] += 1
        self.cost_total_ns += cost
        self.cost_max_ns = max(self.cost_max_ns, cost)
        self.cost_buckets[cost.bit_length()] += 1

    def observe(self, message, entry_ns):
        started = time.monotonic_ns()
        sample = dict(kind='receive', time_ns=entry_ns, entry_ns=entry_ns,
                      generation=message.generation, sequence=message.sequence,
                      simulation_stamp_ns=stamp_ns(message))
        # Complete pending windows before adding a new one. At most context+1 exist.
        for window in list(self.pending):
            window['after'].append(sample)
            if len(window['after']) >= self.context:
                window['complete'] = True
                self._enqueue(window, priority=True)
                self.pending.remove(window)
        if self.last and entry_ns - self.last['entry_ns'] > THRESHOLD_NS:
            gap = dict(kind='receive_gap', time_ns=entry_ns,
                       gap_ns=entry_ns-self.last['entry_ns'],
                       before=list(self.history), current=sample, after=[], complete=False)
            self.counts['receive_gaps'] += 1
            self._enqueue(dict(kind='gap_start', time_ns=entry_ns,
                               gap_ns=gap['gap_ns'], previous=self.last, current=sample), priority=True)
            self.pending.append(gap)
        self._enqueue(sample)
        self.history.append(sample)
        self.last = sample
        self._cost(started)

    def trailing_gap(self, end_ns):
        if self.last and end_ns-self.last['entry_ns'] > THRESHOLD_NS:
            self.counts['trailing_gaps'] += 1
            self._enqueue(dict(kind='trailing_gap', time_ns=end_ns,
                gap_ns=end_ns-self.last['entry_ns'], before=list(self.history), complete=False), priority=True)

    def _write(self):
        written = 0
        writer_cpu_start = time.thread_time_ns()
        writer_wall_start = time.monotonic_ns()
        try:
            with self.path.open('x') as stream:
                while not self.closed.is_set() or not self.priority.empty() or not self.normal.empty():
                    priority = True
                    try:
                        event = self.priority.get_nowait()
                    except queue.Empty:
                        priority = False
                        try:
                            event = self.normal.get(timeout=.02)
                        except queue.Empty:
                            continue
                    if not priority and written >= self.max_records:
                        self.counts['dropped_limit'] += 1
                        continue
                    stream.write(json.dumps(event, separators=(',', ':')) + '\n')
                    written += 1
                stream.write(json.dumps(dict(kind='summary', time_ns=time.monotonic_ns(),
                    counts=dict(self.counts), written_records=written,
                    writer_cpu_ns=time.thread_time_ns()-writer_cpu_start,
                    writer_wall_ns=time.monotonic_ns()-writer_wall_start,
                    enqueue_total_ns=self.cost_total_ns, enqueue_max_ns=self.cost_max_ns,
                    enqueue_cost_log2_ns_buckets=dict(self.cost_buckets))) + '\n')
        except Exception as exc:
            self.error = str(exc)

    def close(self):
        for gap in self.pending:
            self._enqueue(gap, priority=True)
        self.pending.clear()
        self.closed.set()
        self.thread.join(timeout=5.)
        if self.thread.is_alive() or self.error:
            raise RuntimeError('Timing trace flush failed: ' + str(self.error or 'writer deadline'))
