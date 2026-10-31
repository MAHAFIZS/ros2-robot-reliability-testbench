# Four-minute portfolio demonstration

Run from the repository root on a Docker-capable host. Build **before** presenting:

```bash
python3 scripts/build_image.py
```

The four-minute duration is a narrated walkthrough, not an artificial four-minute
simulation. Commands usually finish in well under a minute on the verified host;
allow 3–5 minutes to inspect their evidence. There are no fixed sleeps or new demo
APIs. Existing launch/client workflows perform readiness checks and bounded waits.
No GPU, privileged mode or host Python/build mounts are needed.

## 0:00–0:40 — problem, boundaries and healthy reaching

Show the README architecture table. Explain: raw truth stays intact; the controller
uses it, while the monitor only sees affected observations and task intent.

```bash
docker run --rm --network none robot-reliability:jazzy \
  ros2 run robot_reliability_testbench milestone_b
```

Point to three successful actions, feedback counts and final errors ≤0.005 m.
Keep simulation durations distinct from client wall durations.

## 0:40–1:40 — deliberate faults and recovery

This single container runs the existing fault workflow, explicitly repeats offline
analysis and fresh-monitor replay, then creates a fresh short-run HTML report.
Each later command runs only if the previous command succeeded.

```bash
docker run --name testbench-portfolio --network none robot-reliability:jazzy \
  bash -c 'set -e
    ros2 run robot_reliability_testbench milestone_d \
      --bag-root /workspace/bags/portfolio --reports /workspace/reports/portfolio
    ros2 run robot_reliability_testbench fault_bag_analyze \
      /workspace/bags/portfolio/faults --output /workspace/reports/portfolio/independent-analysis.json
    ros2 launch robot_reliability_testbench fault_replay.launch.py \
      bag:=/workspace/bags/portfolio/faults \
      output:=/workspace/reports/portfolio/explicit-replay.json live_domain:=87 replay_domain:=88
    python -m reliability_testbench.endurance --profile short \
      --output /workspace/reports/portfolio-short'
mkdir -p artifacts/portfolio
docker cp testbench-portfolio:/workspace/reports artifacts/portfolio/
docker cp testbench-portfolio:/workspace/bags artifacts/portfolio/
```

Even on failure, copy the reports/logs. A nonzero exit or `success: false` is a
failed demonstration to investigate, not an invitation to relax thresholds. Keep
the container until artifacts have been exported. It must not share a live ROS
domain/network with an unrelated robot. `--network none` isolates this container;
live and replay also use different ROS domains (87/88).

The six scenario labels include missing observations, frozen observations,
command delay, queued timeout and recovery. Faults are enabled/disabled through
the typed service, not by giving the monitor the fault labels.

## 1:40–2:40 — inspect observations, intent and independent replay

The following uses only the host Python standard library and the exported files:

```bash
python3 - <<'PY'
import json
from pathlib import Path
p = Path('artifacts/portfolio/reports/portfolio')
run = json.loads((p / 'milestone_d.json').read_text())
offline = json.loads((p / 'independent-analysis.json').read_text())
replay = json.loads((p / 'explicit-replay.json').read_text())
assert run['success'] and offline == run['offline']
assert replay['success'] and replay['comparison'] == offline['diagnostic_signature']
assert replay['new_diagnostic_topic'] == '/replay/diagnostics'
assert replay['new_diagnostics'][0]['monitor_session'] != replay['recorded_diagnostics'][0]['monitor_session']
for scenario in run['scenarios']:
    task = scenario['task']
    print(scenario['scenario'], 'scenario_passed=', scenario['passed'],
          'diagnostics=', scenario['observed_codes'],
          'robot_task_success=', task['success'] if task else 'no task')
print('Recorded topics:', len(offline['topics']))
print('Replayed inputs:', replay['replayed_topics'])
print('Fresh diagnostic events:', len(replay['new_diagnostics']))
print('Replay forbidden publishers:', replay['forbidden_published_topics'])
PY
```

Explain these distinctions while showing the printed rows:

- Missing observations trigger **STALE_OBSERVATIONS**, then
  **OBSERVATIONS_RECOVERED** after disable; a sequence gap may also be reported.
- Frozen values during commanded motion trigger **NO_PROGRESS**, then
  **PROGRESS_RECOVERED**. Without independent evidence the monitor cannot prove a
  sensor freeze rather than command delay or blocked motion.
- The queued-timeout scenario passes its safety expectation while its robot task
  has `success: false`: pending targets must not execute later.
- Offline analysis reads actual serialized messages with `rosbag2_py`. The extra
  CLI pass above must agree with the original analysis of the same bag.
- The fresh monitor receives only affected state, intent and recorded clock.
  Raw truth, fault labels and recorded diagnostics are not replay inputs. Recorded
  diagnostics are comparison evidence; new events appear on `/replay/diagnostics`.

The explicit replay launch starts no simulator, task server or command publishers.
It waits for subscribers before resuming playback and uses one replay clock.
Compare reason/lifecycle and gap order, not identical wall timing or arbitrary
interleaving between independent topics.

## 2:40–3:30 — HTML acceptance and test evidence

Open this local file in a browser (no server or dashboard required):

`artifacts/portfolio/reports/portfolio-short/endurance.html`

Show its predeclared acceptance criteria, actual task/error/observation counts,
CPU/RSS scope, failures and limitations. The report has sibling JSON/JUnit files.
Show the separate [85-case regression JUnit](../reports/milestone_e.junit.xml)
and [E HTML](../reports/milestone_e.html); a fresh short workload alone is not a
rerun of all 85 tests. The quick-start default image command reruns that full suite.

## 3:30–4:00 — disclose limits, then clean up

Show [the unresolved 354 ms receive gap](verification.md#the-354-ms-anomaly).
State that this is SIL monitoring with a raw-state controller, not closed-loop
fault robustness. Hosted CI and 30-minute endurance have no verified result;
short resource trends do not prove absence of memory leaks. Do not claim physical
robot testing, HIL or production readiness.

After artifact inspection:

```bash
docker rm testbench-portfolio
```

For another run use a new container or remove the prior stopped one first. Each
new container has fresh bag paths; do not overwrite an existing bag in a reused
container. Bags remain under the ignored `artifacts/portfolio/bags` on the host.
