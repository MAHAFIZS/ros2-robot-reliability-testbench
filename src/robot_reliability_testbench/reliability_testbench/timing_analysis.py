"""Offline sequence-checked join of bounded local timing files."""
import argparse
import json
from pathlib import Path

from .timing_trace import THRESHOLD_NS


def percentile(values, fraction):
    if not values:
        return None
    return sorted(values)[min(len(values)-1, int((len(values)-1)*fraction))]


def describe(values):
    return dict(count=len(values), max_ns=max(values, default=None),
                p50_ns=percentile(values,.5), p99_ns=percentile(values,.99))


def match_stages(sample, sources, boundaries, monitors):
    key = sample['generation'], sample['simulation_stamp_ns']
    source, boundary, monitor = sources.get(key), boundaries.get(key), monitors.get(key)
    if boundary and boundary['sequence'] != sample['sequence']:
        raise ValueError('Boundary/runner sequence mismatch for generation/stamp ' + str(key))
    if monitor and monitor['sequence'] != sample['sequence']:
        raise ValueError('Monitor/runner sequence mismatch for generation/stamp ' + str(key))
    complete = source is not None and boundary is not None and monitor is not None
    result = dict(generation=key[0], simulation_stamp_ns=key[1],
                  boundary_sequence=sample['sequence'], complete=complete,
                  source=source, boundary=boundary, monitor=monitor, runner=sample)
    if complete:
        if not (source['publish_start_ns'] <= boundary['entry_ns'] <= boundary['publish_start_ns'] <= sample['entry_ns']):
            raise ValueError('Noncausal stage starts for matched sequence')
        if monitor['entry_ns'] < boundary['publish_start_ns']:
            raise ValueError('Noncausal monitor receipt')
        result['durations_ns'] = dict(
            source_publish_api=source['publish_end_ns']-source['publish_start_ns'],
            source_to_boundary_entry=boundary['entry_ns']-source['publish_start_ns'],
            boundary_processing=boundary['publish_start_ns']-boundary['entry_ns'],
            boundary_publish_api=boundary['publish_end_ns']-boundary['publish_start_ns'],
            boundary_to_runner_entry=sample['entry_ns']-boundary['publish_start_ns'],
            boundary_to_monitor_entry=monitor['entry_ns']-boundary['publish_start_ns'],
            runner_minus_monitor_entry=sample['entry_ns']-monitor['entry_ns'])
    return result


def analyze(directory):
    directory = Path(directory)
    events = {}
    summaries = {}
    metadata = {}
    for role in ('simulator','boundary','monitor','runner'):
        path=directory/(role+'.jsonl')
        records=[json.loads(line) for line in path.read_text().splitlines()]
        if len(records)>205000:
            raise ValueError('Trace exceeds offline record bound')
        headers=[r for r in records if r['kind']=='metadata']
        footers=[r for r in records if r['kind']=='summary']
        if len(headers)!=1 or len(footers)!=1:
            raise ValueError('Missing/duplicate trace metadata or summary: '+role)
        metadata[role]=headers[0]
        summaries[role]=footers[0]
        events[role]=records
    clocks=[r['clock'] for r in metadata.values()]
    if any(clock!=clocks[0] for clock in clocks[1:]):
        raise ValueError('Timing clocks are not comparable')
    runner=events['runner']
    starts=[r for r in runner if r['kind']=='measurement_start']
    ends=[r for r in runner if r['kind']=='measurement_end']
    if len(starts)!=1 or len(ends)!=1:
        raise ValueError('Incomplete measurement window trace')
    begin,end=starts[0]['start_ns'],ends[0]['end_ns']
    def index(role,kind):
        result={}
        for r in events[role]:
            if r['kind']!=kind:continue
            key=r['generation'],r['simulation_stamp_ns']
            if key in result:raise ValueError('Duplicate generation/stamp in '+role)
            result[key]=r
        return result
    sources=index('simulator','source_publish')
    boundaries=index('boundary','boundary')
    monitors=index('monitor','receive')
    received=[r for r in runner if r['kind']=='receive' and begin<=r['entry_ns']<=end]
    matched=[match_stages(r,sources,boundaries,monitors) for r in received]
    incomplete=sum(not r['complete'] for r in matched)
    samples=[r for r in runner if r['kind']=='resource_sample' and r['end_ns']>=begin and r['start_ns']<=end]
    spins=[r for r in runner if r['kind']=='spin' and r['end_ns']>=begin and r['start_ns']<=end]
    gaps=[]
    for r in runner:
        if r['kind'] not in ('receive_gap','trailing_gap') or not begin<=r['time_ns']<=end+1_000_000:
            continue
        context=r['before']+([r['current']] if 'current' in r else [])+r.get('after',[])
        joined=[match_stages(s,sources,boundaries,monitors) for s in context]
        start=r['time_ns']-r['gap_ns'];stop=r['time_ns']
        overlapping_samples=[s for s in samples if s['end_ns']>start and s['start_ns']<stop]
        gap=dict(event=r,matched_context=joined,resource_sample_overlaps=overlapping_samples,
            spin_overlaps=[s for s in spins if s['end_ns']>start and s['start_ns']<stop])
        if 'current' in r and r['before']:
            a=match_stages(r['before'][-1],sources,boundaries,monitors)
            b=match_stages(r['current'],sources,boundaries,monitors)
            if a['complete'] and b['complete']:
                gap['adjacent_stage_intervals_ns']=dict(
                    source_publish=b['source']['publish_start_ns']-a['source']['publish_start_ns'],
                    simulator_tick=(b['source']['tick_entry_ns']-a['source']['tick_entry_ns']
                        if a['source']['tick_entry_ns'] and b['source']['tick_entry_ns'] else None),
                    boundary_receipt=b['boundary']['entry_ns']-a['boundary']['entry_ns'],
                    boundary_publish=b['boundary']['publish_start_ns']-a['boundary']['publish_start_ns'],
                    monitor_entry=b['monitor']['entry_ns']-a['monitor']['entry_ns'],
                    runner_entry=b['runner']['entry_ns']-a['runner']['entry_ns'])
                # This is overlap evidence, not automatic root-cause inference.
                gap['resource_block_overlap_ns']=sum(max(0,min(stop,s['end_ns'])-max(start,s['start_ns'])) for s in overlapping_samples)
        gaps.append(gap)
    dropped={role:sum(count for key,count in summary['counts'].items() if key.startswith('dropped')) for role,summary in summaries.items()}
    metrics={key:describe([r['durations_ns'][key] for r in matched if r['complete']])
             for key in next((r['durations_ns'] for r in matched if r['complete']),{})}
    overhead={}
    for role,s in summaries.items():
        calls=s['counts'].get('instrumentation_calls',0)
        overhead[role]=dict(calls=calls,total_enqueue_ns=s['enqueue_total_ns'],
            mean_enqueue_ns=s['enqueue_total_ns']/calls if calls else None,
            max_enqueue_ns=s['enqueue_max_ns'],cost_log2_ns_buckets=s['enqueue_cost_log2_ns_buckets'],
            writer_cpu_ns=s.get('writer_cpu_ns'),writer_wall_ns=s.get('writer_wall_ns'),
            writer_cpu_percent=(s['writer_cpu_ns']/s['writer_wall_ns']*100
                                if s.get('writer_wall_ns') else None))
    return dict(clock=clocks[0],clock_comparable=True,matched_observations=len(matched)-incomplete,
        incomplete_matches=incomplete,duplicate_keys_rejected=True,sequence_mismatches=0,
        dropped_records=dropped,coverage_valid=not incomplete and not any(dropped.values()),
        retained_runner_gaps=gaps,retained_monitor_gap_count=sum(r['kind']=='receive_gap' and begin<=r['time_ns']<=end for r in events['monitor']),
        stage_durations=metrics,resource_sampling=describe([r['end_ns']-r['start_ns'] for r in samples]),
        spin_duration=describe([r['end_ns']-r['start_ns'] for r in spins]),
        between_spins=describe([b['start_ns']-a['end_ns'] for a,b in zip(spins,spins[1:])]),
        overhead=overhead,trace_bytes=sum((directory/(role+'.jsonl')).stat().st_size for role in events),
        outcome='receive gaps observed' if gaps else 'not reproduced in short runs',
        limitations=['Publish timestamps bracket Python publish API calls, not network wire time.',
            'Publish-to-callback durations combine transport and executor scheduling; they do not separate them.',
            'Recorder encoding/I/O occurs on writer threads; measured enqueue cost excludes writer CPU and observer effects.',
            'No uninstrumented matched workload was run; incremental end-to-end overhead is not established.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    Path(args.output).write_text(json.dumps(analyze(args.directory),indent=2)+'\n')


if __name__=='__main__':main()
