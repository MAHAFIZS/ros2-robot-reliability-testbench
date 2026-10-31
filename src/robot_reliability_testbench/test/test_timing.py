"""Trace bounds, loss accounting, sequence identity and threshold behavior."""
import json
import threading
from types import SimpleNamespace

import pytest

from reliability_testbench.timing_trace import Trace, THRESHOLD_NS
from reliability_testbench.timing_analysis import match_stages
from reliability_testbench.endurance import acceptance
from test_endurance import healthy


def message(sequence):
    return SimpleNamespace(generation=1,sequence=sequence,
                           stamp=SimpleNamespace(sec=0,nanosec=sequence*20_000_000))


def records(directory):
    return [json.loads(line) for line in (directory/'test.jsonl').read_text().splitlines()]


def test_timing_gaps_keep_sequence_context_and_exact_threshold(tmp_path):
    trace=Trace(tmp_path,'test',context=2)
    trace.observe(message(1),1_000_000_000)
    trace.observe(message(2),1_000_000_000+THRESHOLD_NS)  # Equal is accepted.
    trace.observe(message(3),1_000_000_000+2*THRESHOLD_NS+1)
    trace.observe(message(4),1_000_000_000+2*THRESHOLD_NS+20_000_001)
    trace.observe(message(5),1_000_000_000+2*THRESHOLD_NS+40_000_001)
    trace.close()
    rows=records(tmp_path)
    gap,=[r for r in rows if r['kind']=='receive_gap']
    assert gap['gap_ns']==THRESHOLD_NS+1
    assert [s['sequence'] for s in gap['before']]==[1,2]
    assert gap['current']['sequence']==3
    assert [s['sequence'] for s in gap['after']]==[4,5]
    assert gap['complete']
    assert not any(k.startswith('dropped') for k in rows[-1]['counts'])


def test_timing_flushes_incomplete_window_and_trailing_gap(tmp_path):
    trace=Trace(tmp_path,'test',context=2)
    trace.observe(message(1),1)
    trace.observe(message(2),THRESHOLD_NS+2)
    trace.trailing_gap(2*THRESHOLD_NS+3)
    trace.close()
    rows=records(tmp_path)
    gap,=[r for r in rows if r['kind']=='receive_gap']
    assert not gap['complete'] and not gap['after']
    assert len([r for r in rows if r['kind']=='trailing_gap'])==1


def test_timing_queue_overflow_counted_without_callback_io(tmp_path,monkeypatch):
    original=Trace._write
    gate=threading.Event()
    def paused(self):
        assert gate.wait(timeout=3)
        original(self)
    monkeypatch.setattr(Trace,'_write',paused)
    trace=Trace(tmp_path,'test',capacity=1)
    try:
        for i in range(10):trace.emit('sample',sequence=i)
        assert not (tmp_path/'test.jsonl').exists()
    finally:
        gate.set();trace.close()
    assert records(tmp_path)[-1]['counts']['dropped_queue']==10


def test_timing_record_limit_reported(tmp_path):
    trace=Trace(tmp_path,'test',max_records=1)
    trace.emit('sample')
    trace.close()
    assert records(tmp_path)[-1]['counts']['dropped_limit']==1


def test_timing_joins_actual_boundary_sequence_not_source_counter():
    key=(1,20)
    source=dict(publish_start_ns=100,publish_end_ns=120,source_sequence=29)
    boundary=dict(sequence=5,entry_ns=110,publish_start_ns=130,publish_end_ns=145)
    monitor=dict(sequence=5,entry_ns=150)
    runner=dict(generation=1,simulation_stamp_ns=20,sequence=5,entry_ns=155)
    result=match_stages(runner,{key:source},{key:boundary},{key:monitor})
    assert result['complete'] and result['source']['source_sequence']==29
    assert result['durations_ns']['boundary_processing']==20
    with pytest.raises(ValueError,match='sequence mismatch'):
        match_stages(dict(runner,sequence=6),{key:source},{key:boundary},{key:monitor})
    assert not match_stages(dict(runner,generation=2),{key:source},{key:boundary},{key:monitor})['complete']


def test_timing_sampling_disabled_does_not_waive_acceptance():
    report=healthy()
    report['resources']=[]
    failed={c['name'] for c in acceptance(report) if not c['passed']}
    assert failed=={'resources_collected','all_nodes_measured','per_process_rss_bound'}
    assert report['configuration']['max_observation_gap_seconds']==.15
