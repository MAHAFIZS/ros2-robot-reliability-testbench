#!/usr/bin/env python3
"""Six alternating bounded experiments; never execute the 30-minute profile."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from reliability_testbench.timing_analysis import analyze


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='/workspace/reports/timing-comparison')
    args=parser.parse_args()
    root=Path(args.output).resolve()
    root.mkdir(parents=True,exist_ok=True)
    results=[]
    for index in range(6):
        enabled=index%2==0
        directory=root/f'{index+1:02d}-sampling-{"on" if enabled else "off"}'
        if directory.exists():raise RuntimeError('Refusing to overwrite '+str(directory))
        directory.mkdir()
        command=[sys.executable,'-m','reliability_testbench.endurance','--duration-seconds','60',
                 '--seed','7','--timing','--output',str(directory)]
        if not enabled:command.append('--disable-resource-sampling')
        print('Starting',directory.name,flush=True)
        with (directory/'runner.log').open('w') as log:
            process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
            try:code=process.wait(timeout=100)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:process.wait(timeout=18)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
                raise RuntimeError('Bounded experiment timeout: '+directory.name)
        report=json.loads((directory/'endurance.json').read_text())
        trace=analyze(directory/'timing')
        (directory/'timing-analysis.json').write_text(json.dumps(trace,indent=2)+'\n')
        entry=dict(run=directory.name,resource_sampling=enabled,exit_status=code,
                   report=report,timing=trace)
        results.append(entry)
        (root/'comparison.json').write_text(json.dumps(dict(experiments=results),indent=2)+'\n')
        print('Finished',directory.name,'exit',code,'gaps',len(trace['retained_runner_gaps']),
              'coverage',trace['coverage_valid'],flush=True)
        if code not in (0,1) or report['failures'] or not trace['coverage_valid']:
            raise RuntimeError('Incomplete/invalid experiment; inspect '+str(directory))
    summary=dict(experiments=results,design=dict(order='on/off/on/off/on/off',runs=6,
        duration_seconds_each=60,seed=7,max_observation_gap_seconds=.15,
        unchanged_acceptance=True,disabled_runs='diagnostic experiments, not replacement endurance; missing-resource criteria remain failed'),
        gap_reproduced=any(r['timing']['retained_runner_gaps'] for r in results),
        root_cause='Not automatically inferred; examine matched timing evidence before changing sampling')
    (root/'comparison.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
