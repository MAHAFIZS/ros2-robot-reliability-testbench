#!/usr/bin/env python3
"""Container regression/smoke entrypoint, always emitting aggregate reports."""
import argparse
import datetime
import html
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import psutil


def cleanup():
    children = psutil.Process().children(recursive=True)
    for child in children:
        try:
            child.send_signal(signal.SIGINT)
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(children, timeout=10)
    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='/workspace/reports/ci')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['TESTBENCH_REPORT_DIR'] = str(output / 'regression')
    Path(os.environ['TESTBENCH_REPORT_DIR']).mkdir(exist_ok=True)
    phases = []
    failure = None
    def execute(name, command, timeout, expected=0):
        start = time.monotonic()
        with (output / (name + '.log')).open('w') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                cleanup()
                code = 124
        phases.append(dict(name=name, command=command, exit_status=code,
                           expected_exit_status=expected, passed=code == expected,
                           wall_seconds=time.monotonic() - start))
        if code != expected:
            raise RuntimeError(name + ' returned ' + str(code))
    try:
        execute('regression', [sys.executable, '-m', 'pytest', '/workspace/src/robot_reliability_testbench/test',
            '-q', '--junitxml=' + str(output / 'regression.junit.xml')], 360)
        execute('short', [sys.executable, '-m', 'reliability_testbench.endurance', '--profile', 'short',
            '--output', str(output / 'short')], 70)
        execute('intentional_failure', [sys.executable, '-m', 'reliability_testbench.endurance',
            '--duration-seconds', '8', '--min-tasks', '1000000', '--output', str(output / 'intentional_failure')], 60, expected=1)
        negative = json.loads((output / 'intentional_failure/endurance.json').read_text())
        if negative['failures'] or negative['success'] or not any(c['name'] == 'minimum_tasks' and not c['passed'] for c in negative['criteria']):
            raise RuntimeError('Negative control failed for an unintended infrastructure reason')
    except Exception as exc:
        failure = str(exc)
    finally:
        cleanup()
        report = dict(executed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            success=failure is None, phases=phases, failure=failure,
            limitations=['Hosted GitHub execution is separate from this local container execution.',
                         'The intentionally failing workload is a negative acceptance test, not a robot fault scenario.'])
        (output / 'checks.json').write_text(json.dumps(report, indent=2) + '\n')
        suite = ET.Element('testsuite', name='container_checks', tests=str(len(phases)),
                           failures=str(sum(not p['passed'] for p in phases)))
        for phase in phases:
            case = ET.SubElement(suite, 'testcase', name=phase['name'], time=str(phase['wall_seconds']))
            if not phase['passed']:
                ET.SubElement(case, 'failure').text = json.dumps(phase)
        if failure and all(p['passed'] for p in phases):
            case = ET.SubElement(suite, 'testcase', name='orchestration')
            ET.SubElement(case, 'failure').text = failure
            suite.set('tests', str(len(phases) + 1))
            suite.set('failures', '1')
        ET.ElementTree(suite).write(output / 'checks.junit.xml', encoding='utf-8', xml_declaration=True)
        (output / 'checks.html').write_text('<!doctype html><meta charset="utf-8"><title>Container checks</title><h1>' +
            ('PASS' if report['success'] else 'FAIL') + '</h1><p><a href="short/endurance.html">Measured healthy workload</a></p>' +
            '<p><a href="intentional_failure/endurance.html">Negative control</a></p><pre>' + html.escape(json.dumps(report, indent=2)) + '</pre>')
    return 0 if failure is None else 1


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise RuntimeError('Interrupted by ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    raise SystemExit(main())
