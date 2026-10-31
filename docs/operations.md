# Operational reference (milestones A–E)

Detailed commands and historical A–E evidence. Start with the [portfolio README](../README.md).
The [F evidence review](verification.md) qualifies the earlier pause wording: source publication timing was not captured.

Independent portfolio project: headless software-in-the-loop Cartesian reaching
with a simulated Panda. **Milestones A–E are implemented.** No physical
robot connection, hardware validation, grasping or perception is involved.

## Milestone E: container, CI and healthy endurance

Build from this repository using Python's standard library and Docker:

```bash
python3 scripts/build_image.py
docker run --name testbench-checks --network none robot-reliability:jazzy
mkdir -p artifacts
docker cp testbench-checks:/workspace/reports artifacts/
docker cp testbench-checks:/opt/testbench artifacts/dependencies
docker rm testbench-checks
```

The default command runs the complete regression suite, the short healthy
endurance profile, and an intentionally failing acceptance check. The wrapper
requires that negative control to return **1**, with `minimum_tasks` failed and
no infrastructure failures. The wrapper itself returns **0** only when all
three phases meet their expected outcomes. JSON, JUnit XML, HTML and launch/test
logs are under `artifacts/reports/ci`; build and resolved dependency manifests
are under `artifacts/dependencies`. Preserve a failed container until its reports
have been copied. No host Python, build or install directories are mounted.
There is no privileged mode, GPU, display or host networking requirement.

Run just the short profile, or a launch-based demonstration:

```bash
docker run --name testbench-short --network none robot-reliability:jazzy \
  python -m reliability_testbench.endurance --profile short --output /workspace/reports/short
docker cp testbench-short:/workspace/reports artifacts/
docker rm testbench-short
docker run --rm --network none robot-reliability:jazzy \
  ros2 run robot_reliability_testbench milestone_b
```

The local endurance profile measures **1800 seconds of steady wall time**,
excluding bounded readiness/warmup and shutdown. It has not been run automatically.
Its exact command, after building the image, is:

```bash
mkdir -p artifacts
docker run --name testbench-30m --network none robot-reliability:jazzy \
  python -m reliability_testbench.endurance --profile local --seed 7 \
  --output /workspace/reports/endurance-30m
docker cp testbench-30m:/workspace/reports artifacts/
docker rm testbench-30m
```

To see a failing acceptance report directly (expected exit status 1):

```bash
docker run --name testbench-negative --network none robot-reliability:jazzy \
  python -m reliability_testbench.endurance --duration-seconds 8 --min-tasks 1000000 \
  --output /workspace/reports/negative
docker cp testbench-negative:/workspace/reports artifacts/
docker rm testbench-negative
```

Acceptance is written to `acceptance.before_run.json` before launch. Defaults:
short 18 wall seconds / at least 10 completed tasks; local 1800 seconds / at least
1000; 100% action success, final errors ≤0.005 m, each task ≤6 steady seconds,
no missing observation sequences, no receive interval above 0.15 steady seconds,
no diagnostic events or fault changes during measurement, all four ROS processes
measured at least twice, and each process peak RSS ≤512 MiB. Every criterion must
pass. Last six seconds reserve bounded action completion and continue monitoring;
there are no new goals in that interval. Three known reachable Cartesian targets
are selected with seed 7, avoiding consecutive identical targets. The controller
tolerance remains 5 mm even when report acceptance is overridden.
The seed fixes the target sequence prefix; scheduling determines how many goals
finish within the wall-time window, so identical task counts or wall timings are
not required across runs.

Readiness checks discover the action/services and affected observations; reset
and 0.5 simulation seconds of healthy observations warm the monitor before
measurement. Tasks use simulation duration from the action result. Observation
intervals retain both simulation stamps and steady receive times. Endurance wall
duration uses `time.monotonic()`, independent of `/clock`. ROS startup and task
waits are bounded. SIGINT/SIGTERM and failures trigger cleanup of the owned launch
tree, including descendants in separate sessions. A failed build, regression,
task or criterion returns nonzero.

Resources cover the **ros2 launch process and all its descendants** (the simulator,
task server, fault boundary and independent monitor); they exclude the runner,
Docker daemon, kernel and unrelated host processes. Approximately one sample per
steady second records process CPU time and RSS. Reports include initial/final/peak
RSS, endpoint change and MiB/minute trend, and mean/peak CPU percent. CPU can exceed
100% for multithreaded processes. No memory-leak conclusion follows from a short
run. Observations and CPU samples are aggregated online; individual task results
are retained. Healthy endurance does not inject faults; expected fault outcomes
remain in the separate D regression reports.

The image pins the Jazzy/Ubuntu base by digest, direct apt dependencies in
`docker/apt-packages.lock`, and Python dependencies (including transitives) in
`requirements.txt` by version.
It includes the repository's hash-verified Panda assets with their original
Apache-2.0 license and `SOURCE.json`. The container creates its own Python 3.12
environment at `/opt/venv` and compiles both packages. `/opt/testbench` contains
the exact resolved apt and Python versions and build log. Apt repositories are
external build inputs; their future availability is not guaranteed. The source
build helper records Git revision, dirty state and a SHA-256 of code/build inputs;
an unborn Git repository is reported with a null revision, never a fabricated SHA.
`.dockerignore` excludes host environments, builds, install trees, bags, reports
and credentials. Generated bags stay inside `/workspace/bags` or temporary test
directories and are not uploaded by CI. Host `bags/` and bulky `artifacts/` are
ignored by Git.

The [GitHub workflow](../.github/workflows/regression.yml) builds the image, runs
these checks without external networking, uses a 20-minute job timeout and
uploads reports/logs even on failure. Python phase timeouts bound regression and
smoke runs; the container's init process reaps children. Hosted CI requires a push
to GitHub and is not implied by local verification. See the
[E requirement-to-test matrix](../docs/milestone_e_test_matrix.md) and
[measured E report](../reports/milestone_e.json) for executed checks and limitations.

Local container verification passed **85 tests: the original 64 plus 21 new E
cases**. The final short run reached 34/34 targets successfully, with maximum
error 4.9143 mm, 18.0086 measured wall seconds, 18.0400 simulation seconds,
902 affected observations, no sequence gaps and no diagnostics. The negative
control returned 1; the complete check wrapper returned 0. The three-target
launch demo also passed. Container versions include Python 3.12.3, rclpy 7.1.12,
rosbag2_py 0.26.11 and the pinned Python requirements. See the
[readable summary](../reports/milestone_e.html),
[short-run report](../reports/milestone_e.short.html) and
[JUnit results](../reports/milestone_e.junit.xml).

An earlier short run **failed correctly** on a 353.8 ms observation-receive pause,
emitting STALE_OBSERVATIONS and OBSERVATIONS_RECOVERED despite all 35 robot tasks
succeeding. Its measurements remain in
[the failed freshness report](../reports/milestone_e.observation_gap.json).
An independent repeat and the final full verification passed unchanged criteria.
The pause's root cause remains unresolved: a separate 40-target physics probe
had maximum IK time 1.38 ms, and a NumPy probe used one thread. These probes do
not prove the cause of the earlier pause. Hosted CI, real-time guarantees and
30-minute resource stability remain unverified.

## Environment and reuse

Verified on 2026-10-31: Ubuntu 24.04.4, ROS 2 Jazzy, `rclpy` 7.1.11,
Python 3.12.3, MuJoCo 3.16.0, NumPy 1.26.4, pytest 7.4.4. Docker CLI 29.1.3
was the host CLI used for milestone E. See the E report for container verification;
the earlier A–D measurements retain their original environments. No host system
dependencies were changed. No AGENTS.md was present in this workspace.

The existing separate `robot-data-pipeline` project supplied the pinned model
assets and the damped Jacobian IK / position-actuator bias-compensation approach
adapted from `robotics_dataset/franka.py`. Its cube, camera, teleoperation and
HDF5 pipeline are outside this project. This project imports none of its code.

Unmodified model files are in `src/robot_reliability_testbench/models`.
The [manifest](../models/franka_emika_panda/SOURCE.json) pins MuJoCo Menagerie
commit `62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35`. Every model file's SHA-256
is checked on initialization. The upstream [Apache-2.0 license](../models/franka_emika_panda/LICENSE)
and attribution are retained. Position refers to the no-hand model's
`attachment_site` in `world`, in metres. Orientation is reported but not controlled.

## Build and source

Use Python **3.12** for Jazzy's installed bindings. The shell's default Python
3.13 is incompatible. Use a workspace-local environment, or the self-contained
Docker commands below. No external project environment is required:

```bash
source /opt/ros/jazzy/setup.bash
/usr/bin/python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.txt
export TESTBENCH_PYTHON="$PWD/.venv/bin/python"
"$TESTBENCH_PYTHON" -m colcon build --base-paths src \
  --cmake-args -DPython3_EXECUTABLE="$TESTBENCH_PYTHON" \
               -DPYTHON_EXECUTABLE="$TESTBENCH_PYTHON"
source install/setup.bash
export ROS_LOG_DIR=/tmp/reliability-testbench-ros-logs
export ROS_DOMAIN_ID=87
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
```

For native builds the installation recipe assumes
Jazzy ROS base, colcon, ament_python, ament_cmake, rosidl_default_generators,
launch_ros and rosgraph_msgs are installed. Colcon does not install pip
dependencies. The setuptools `setup.py install` deprecation warning from
Jazzy's ament_python tooling is nonfatal; both packages built successfully.

## Launch and client commands

Start the installed system in one terminal with the environment above:

```bash
ros2 launch robot_reliability_testbench normal.launch.py
```

The Python launch file starts the simulator, task server, fault boundary and
independent health monitor, and loads
[`normal.yaml`](../src/robot_reliability_testbench/config/normal.yaml).
To use another configuration, copy that YAML, retain its fully qualified node
names, and add `params_file:=/absolute/path/config.yaml` to the launch command.
Use the same sourced environment and ROS domain in every client terminal.

```bash
ros2 action send_goal /testbench/reach reliability_interfaces/action/Reach \
  '{target: {x: 0.5945, y: 0.03, z: 0.5945}}' --feedback
ros2 service call /testbench/health reliability_interfaces/srv/Health '{}'
ros2 service call /testbench/reset reliability_interfaces/srv/Reset '{}'
ros2 param get /testbench/task_server target_tolerance
ros2 param set /testbench/task_server target_tolerance 0.001
ros2 param set /testbench/task_server target_tolerance 0.0  # rejected
ros2 param set /testbench/task_server target_tolerance 0.005
ros2 topic echo /testbench/raw/ee_pose --once
```

Cancellation uses the standard action client API:
`handle = await client.send_goal_async(goal)`, then
`await handle.cancel_goal_async()` and `await handle.get_result_async()`.
An executable example is `test_ros_cancel` in
[`test_ros.py`](../src/robot_reliability_testbench/test/test_ros.py).
Stopping a client process alone is not a server cancellation request.

## Architecture and ROS interfaces

`MuJoCo simulator → raw state → task server → command boundary → simulator`

`raw observations → fault boundary → affected observations → independent monitor`

`task server → task intent → independent monitor`

The simulator exclusively owns mutable physics and IK state. Its single-threaded
executor serializes stepping, target commands and reset. The task server is a
separate process with a single-threaded executor and a reentrant action/service
callback group. Its action coroutine awaits a result future; it never sleeps
or blocks an executor thread. Steady timer callbacks advance the lifecycle while
state, cancellation, parameter and reset callbacks continue. Do not substitute
a multithreaded executor without adding synchronization.

| Interface | Type | Purpose |
| --- | --- | --- |
| `/testbench/raw/joint_states` | `sensor_msgs/msg/JointState` | Seven simulated positions and velocities |
| `/testbench/raw/ee_pose` | `geometry_msgs/msg/PoseStamped` | Attachment pose in `world` |
| `/testbench/simulation_state` | `reliability_interfaces/msg/SimulationState` | Atomic pose, joints, generation and physics time |
| `/testbench/task_events` | `reliability_interfaces/msg/TaskEvent` | Timestamped lifecycle, goal ID, target and terminal snapshot |
| `/clock` | `rosgraph_msgs/msg/Clock` | Simulation clock; resets to zero |
| `/testbench/reach` | `reliability_interfaces/action/Reach` | Target; distance/progress/time feedback; success/error/time/reason result |
| `/testbench/reset` | `reliability_interfaces/srv/Reset` | Coordinated reset and restored joint configuration |
| `/testbench/health` | `reliability_interfaces/srv/Health` | Readiness, state age, finite-state check and lifecycle status |
| `/testbench/internal/control` | `reliability_interfaces/srv/Control` | Simulator target/hold, with generation and sequence checks |
| `/testbench/internal/reset` | `reliability_interfaces/srv/Reset` | Simulator-owned reset implementation |
| `/testbench/observed/state` | `reliability_interfaces/msg/ObservedState` | Affected pose/joints with source sequence and generation |
| `/testbench/observed/joint_states` | `sensor_msgs/msg/JointState` | Fault-affected joint observations |
| `/testbench/observed/ee_pose` | `geometry_msgs/msg/PoseStamped` | Fault-affected pose observations |
| `/testbench/task_intent` | `reliability_interfaces/msg/TaskIntent` | Target, tolerance and active-goal intent; no raw pose or fault labels |
| `/testbench/configure_faults` | `reliability_interfaces/srv/ConfigureFaults` | Validated complete fault configuration |
| `/testbench/observation_health` | `reliability_interfaces/srv/MonitorStatus` | Independent monitor readiness, active reasons and counters |
| `/testbench/diagnostics` | `reliability_interfaces/msg/DiagnosticEvent` | Independent diagnosis transitions with evidence |
| `/testbench/fault_events` | `reliability_interfaces/msg/FaultEvent` | Timestamped configuration, seed and activation/deactivation fields |
| `/testbench/command_events` | `reliability_interfaces/msg/CommandEvent` | Queue, forwarding, application and purge timing |

`reliability_interfaces` is an ament_cmake/rosidl package.
`robot_reliability_testbench` is an ament_python package with installed scripts,
launch/YAML files and model assets. Root `reliability_testbench`, `models` and
`tests` symlinks preserve source commands. Installed nodes load assets from
the ament share directory and do not depend on the current directory.

## Parameters and lifecycle

| Node | Parameter | Default | Validation and updates |
| --- | --- | --- | --- |
| simulator | `publication_rate` | 50 Hz | Startup only; finite 1–500 Hz |
| simulator | `initial_joint_positions` | upstream seven-joint home | Startup only; seven finite joints within model limits |
| task server | `target_tolerance` | 0.005 m | Runtime; finite positive float, including during active goals |
| task server | `task_timeout` | 5 simulated seconds | Runtime; finite positive float, snapshotted at acceptance |
| task server | `infrastructure_timeout` | 3 steady seconds | Startup only; finite positive float |
| task server | `use_sim_time` | true in launch YAML | Standard ROS parameter; keep enabled for normal operation |

Only one goal may be active. Its slot is reserved before acceptance; concurrent
goals are rejected while busy or resetting. Nonfinite targets, coordinates
outside a conservative ±1.5 m bound, and targets that bounded IK cannot solve
within 1 mm are rejected before acceptance. IK rejection is conservative, not
proof of global unreachability. The simulator validates again against its current
state and may abort an accepted goal if it cannot solve the command.

Cancellation sends a higher-sequence hold command and returns CANCELED after
acknowledgement. Timeout sends a hold and returns ABORTED. The actuators hold
the sampled joint configuration; this is not an instantaneous zero-velocity
brake. Success uses one received pose within tolerance; actuators then continue
settling at the target. Progress is the clipped fractional reduction in initial
distance, not a trajectory fraction, and need not increase monotonically.

Reset rejects new goals while restoring configured initial joints, zero
velocities, controller targets, simulation time and fractional step credit.
It increments a generation counter, invalidating old commands and observations.
An active goal becomes **ABORTED** with a reset reason. Reset replies after the
simulator acknowledges restoration. A new goal also requires a post-reset
observation. Cancel/timeout results use the simulator's hold snapshot; reset
results use the snapshot immediately before restoration, rather than reporting
error from the restored pose. A previously terminal goal retains its result;
reset takes precedence for a still-active goal. Concurrent reset requests are
rejected. In milestone D, reset also disables all faults, clears freeze snapshots
and drop phases, and purges pending delayed commands before resetting physics.

Internal service names are implementation interfaces, not access controls.
Use the public reset service. An internal simulator reset is detected through
the generation check and aborts an active goal. Restart the entire launch
together: restarting only the task server can invalidate its command sequence
relative to a running simulator.

## Simulation time, wall time and health

Physics integrates in 2 ms steps. A steady-clock timer requests publication
at the configured rate; fractional credit distributes whole physics steps for
rates that do not divide 500 Hz. Scheduler delays slow simulation relative to
wall time rather than skipping physics. Normal launch headers and `/clock`
use MuJoCo simulation timestamps. The task server calculates goal duration and
task timeout from simulation time in atomic state messages. Reset starts a new
generation and moves `/clock` backwards to zero.

Service readiness, state receipt age, command acknowledgements and reset
watchdogs use `time.monotonic()` or ROS's steady clock. A stopped source does
not disable the infrastructure watchdog when `/clock` stops. Health reports
source freshness and finite values, not frozen-value detection or safety
certification. Receipt age is wall time, not subtraction of a simulation stamp
from a wall clock. A deliberate short deadline tests task timeout; stalled-
process watchdog paths are implemented but have not been integration-tested.

The legacy milestone A demo retains system-time headers and its original
five-second steady deadline. Its two nodes share a process. Use normal launch
for milestone B simulation-time semantics.

## Tests and measured demo

Stop any manual launch first. Tests and demo launch and stop their own processes;
run them sequentially in an otherwise unused ROS domain.

```bash
"$TESTBENCH_PYTHON" -m colcon test --base-paths src \
  --return-code-on-test-failure --event-handlers console_direct+ --pytest-args -q
"$TESTBENCH_PYTHON" -m colcon test-result --verbose
# Or, from the workspace root:
"$TESTBENCH_PYTHON" -m pytest -q tests --junitxml=reports/current_suite.junit.xml
# Standalone launch demo: health/reset and three feedback-enabled reaches.
"$TESTBENCH_PYTHON" -m reliability_testbench.milestone_b_demo
# Original A demo (overwrites its measured JSON with the new run):
"$TESTBENCH_PYTHON" -m reliability_testbench.demo
```

Tests exercise real installed launch processes with independent ROS clients.
They use service discovery, received state, futures and bounded spins, with no
fixed startup sleeps. Test reports default to workspace `reports`; override
with `TESTBENCH_REPORT_DIR`. Colcon's JUnit is
`build/robot_reliability_testbench/pytest.xml`. The standalone demo writes its
own JSON and appends its measurements to an existing milestone B JSON report.

| Requirement | Test / artifact |
| --- | --- |
| Original A physics and target validation | Original four cases in `test_simulation.py` retained |
| Several ROS targets and feedback while stepping continues | Three `test_ros_success_and_feedback` cases |
| Invalid, huge finite and unreachable targets | Four `test_ros_invalid_goal_rejected` cases |
| Cancellation and simulated timeout | `test_ros_cancel`, `test_ros_simulation_timeout` |
| Reject overlapping goals | `test_ros_concurrent_goal_rejected` |
| Reset active goal, exact home, stale-command rejection, recovery | `test_ros_reset_active_goal_and_stale_command`, three reset interleavings |
| Health and accepted/rejected runtime parameter values | `test_ros_health_and_parameters` |
| Tolerance update during execution | `test_ros_parameter_update_during_goal` |
| Nondefault initial joints, reset and invalid initial joints | Four additional physics/configuration cases |
| Separate measured launch demo | `reports/milestone_b.demo.json` and demo launch log |

The milestone B colcon run passed **21 pytest cases**, retaining the 5 mm default.
Three healthy integration targets finished at 4.6–4.9 mm error. Runtime tests
also reached within a stricter 1 mm tolerance. The separate launch demonstration
reached all three targets at **4.934, 4.607 and 4.659 mm**, respectively, using
**0.24, 0.32 and 0.30 simulation seconds** and approximately **0.252, 0.336
and 0.311 wall seconds**. Feedback arrived for each goal.

Actual per-action values, timing, test outcomes and demo results are in
[milestone_b.json](../reports/milestone_b.json), with
[JUnit](../reports/milestone_b.junit.xml), [launch logs](../reports/milestone_b.launch.log)
and `reports/milestone_b.build.log`. Both launched processes exited cleanly.
These are short local tests, not endurance or cross-host repeatability evidence.
Milestone A's historical [JSON](../reports/milestone_a.json) and original JUnit
remain available: 4.934 mm against 5 mm, about 0.238 seconds wall time.
The installed A demo also passed from outside the workspace; its separate
[regression result](../reports/milestone_a_regression.json) preserves the historical
artifact while verifying installed model lookup.

## Milestone C: recording, analysis and isolated replay

The installed Jazzy `rosbag2_py` **0.26.10** API was inspected before
implementation, including `SequentialReader.read_next()`, `SequentialWriter`,
storage options and recorder/player controls. `ros2 bag record/play --help`
confirmed paused playback, topic filtering, QoS overrides and acknowledgement
waits. Existing SQLite3 and MCAP plugins were present; no dependencies were
installed or changed. The verified automated path uses **SQLite3**, reliable
volatile QoS with depth 1000, and explicit topic selection:

| Recorded and replayed topic | Content |
| --- | --- |
| `/testbench/raw/joint_states` | Raw simulated joint positions/velocities |
| `/testbench/raw/ee_pose` | Raw end-effector pose |
| `/testbench/simulation_state` | Pose, joints, generation and physics time together |
| `/clock` | The live simulator's simulation clock, including resets |
| `/testbench/task_events` | Explicit lifecycle events; no action transport introspection needed |

`TaskEvent` carries a simulation timestamp, task-server session ID, increasing
sequence number, goal identifier, target, position snapshot, error, tolerance,
simulation duration and same-process monotonic wall duration. Accepted action
goals use the action UUID as hex. An idle reset uses `reset:<operation UUID>`;
an active-goal reset retains that goal's UUID. Event sequences are:

- Success: `ACCEPTED → TARGET → COMPLETED` (`outcome=succeeded`).
- Cancel: `ACCEPTED → TARGET → CANCELED → COMPLETED` (`outcome=canceled`).
- Timeout: `ACCEPTED → TARGET → TIMEOUT → COMPLETED` (`outcome=timeout`).
- Other aborts: `ABORTED → COMPLETED`, with the terminal reason.
- Reset of an active goal: `ABORTED → COMPLETED → RESET` after acceptance/target.
  Terminal measurements describe the pre-reset state. `RESET` uses the new
  generation and zero simulation stamp, with `has_position=false`.

`TARGET` records the requested Cartesian target when accepted, not proof of
actuator execution. Terminal events use the same position snapshot and duration
as the action result. Rejected goals produce no accepted-goal events. Events
are reliable but volatile: the recorder must subscribe before goals start.

### Automated workflow

With the build/source/domain environment above, stop any manual live launch,
then run:

```bash
"$TESTBENCH_PYTHON" -m reliability_testbench.bag_workflow \
  --bag-root "$PWD/bags/manual_c_run_01" --reports "$PWD/reports" --replay-domain 88
```

Choose an unused bag root; the workflow refuses to overwrite bags. It launches
the live system in the current domain (87 in these examples), records three
healthy reaches, then records cancellation during commanded motion. Each
scenario is independently analyzed and replayed in domain 88 **while the live
system remains running in domain 87**. It saves actual action-client measurements
for comparison, but the offline analyser never reads those measurements.

The workflow waits for all recorder subscriptions, checks reliable QoS and
calls the recorder's `is_paused` service before resetting/sending goals. It
uses a SQLite no-cache persistence barrier to wait for the last `COMPLETED`
event to be committed, then sends SIGINT, waits for clean recorder exit, and
opens the finalized bag through `rosbag2_py`. No fixed startup/drain sleep is
used. Read-only SQLite access is used only for that live persistence barrier;
all offline analysis reads/deserializes messages with `rosbag2_py`.

### Manual recording

Start normal launch in one terminal. In a second sourced terminal with the
same domain, start the recorder before sending goals:

```bash
export TESTBENCH_SHARE="$(ros2 pkg prefix --share robot_reliability_testbench)"
ros2 bag record -s sqlite3 -o bags/manual_capture \
  --storage-preset-profile resilient \
  --disable-keyboard-controls --max-cache-size 0 \
  --qos-profile-overrides-path "$TESTBENCH_SHARE/config/bag_qos.yaml" \
  --topics /testbench/raw/joint_states /testbench/raw/ee_pose \
           /testbench/simulation_state /testbench/task_events /clock
```

Wait for **all five** subscription log messages and `All requested topics are
subscribed`. In a third sourced terminal confirm recording is not paused:

```bash
ros2 service call /rosbag2_recorder/is_paused rosbag2_interfaces/srv/IsPaused '{}'
# Require paused: false, then use the reset/action commands above.
```

Wait for the goal result before stopping the recorder with Ctrl-C, and wait for
`Recording stopped`/process exit before analysis. Manual stopping lacks the
automated persistence barrier; analysis will reject missing terminal events.
Do **not** use recorder `--use-sim-time`: this workflow keeps bag receive
timestamps in system time so simulation resets do not reorder the recording.

### Offline analysis

No live ROS processes or network are needed:

```bash
"$TESTBENCH_PYTHON" -m reliability_testbench.bag_analysis bags/manual_capture \
  --output reports/manual.analysis.json
```

The installed `bag_analyze` entry point provides the same CLI. Analysis uses
`SequentialReader`, `get_message` and `deserialize_message` on actual CDR data.
JSON contains counts/types/content hashes, first/last/min/max timestamps,
interval min/max/mean/median and backwards-jump counts, complete task events,
reconstructed outcomes and final errors. Final error is independently computed
from recorded target and position, and the report identifies matching atomic
state snapshots by generation and timestamp.

Missing directories/metadata, unreadable storage, missing/wrong/empty required
topics, corrupt/nonfinite messages, event gaps/reordering, incomplete goals and
inconsistent terminal errors fail with a clear error and nonzero CLI exit.
All five topics are required for this live configuration. Captures must contain
at least one complete goal; a recording that starts halfway through a goal is
rejected. Legacy A recordings without task events are not supported. Extra
topics are reported and ignored by analysis and excluded from replay.

### Observation-only replay

Keep the client shell's live domain at 87. The launch file assigns **88 only
to its replay child**, and refuses equal/out-of-range live/replay IDs:

```bash
ros2 launch robot_reliability_testbench replay.launch.py \
  bag:="$PWD/bags/manual_capture" output:="$PWD/reports/manual.replay.json" \
  live_domain:=87 replay_domain:=88
```

This starts only an observation monitor and a native rosbag player. It starts
no simulator, task server, controller, action client or command publisher. The
player receives an explicit five-topic allowlist, starts paused, and uses
reliable QoS. Subscriptions are created first; replay waits for the player
publishers and resume service, checks there is exactly one player publisher
per observation topic, and rejects a live testbench/command graph before resume.
An acknowledgement wait and bounded subscriber drain protect the playback tail.

The **recorded `/clock` is replayed**. No `--clock`, `--clock-topics` or synthetic
clock is enabled, so bag receive epoch timestamps never become simulated time.
The monitor reads `/clock` as an observation and uses steady deadlines; it
does not perform live task execution or live freshness checks. The workflow
samples the still-running live graph to verify that replay nodes are absent
there, its clock publisher count stays one, and live health remains good.
This is verified DDS-domain isolation on this local setup, assuming no external
domain bridge/router. Domain selection is not a security boundary.

### Comparison rules, timing and actual evidence

- Bag receive timestamps are recorder **system-time nanoseconds**, not simulation
  time. They schedule replay. Their ranges/intervals include transport and
  recorder scheduling. They are not the action client's stopwatch.
- Header/event/clock stamps describe **simulation time** and may move backwards
  at resets. Whole-bag stamp span is not total task simulation duration. Task
  durations come from the recorded terminal event's MuJoCo elapsed field.
- Event wall durations use the task server's monotonic clock. Original client
  wall durations also include request/result transport. Neither must match
  replay wall duration; no identical wall timing is asserted.
- Goal ID/outcome must match exactly. Recomputed final error must match the
  action result within **1e-9 m**, and simulation duration within **1e-9 s**.
  Snapshot timestamp conversion uses a **1 ns** tolerance. The reach success
  criterion stays **5 mm**; the comparison tolerance does not change it.
- Replay requires exact per-topic counts and canonical message-content/order
  SHA-256 hashes, plus exact task-event sequence/order. It does not require a
  global order across independently published topics. A task-server session has
  one event publisher; the first captured sequence can exceed one, but subsequent
  events must be consecutive. Wall-clock jumps during capture are not validated.
- Recorder subscriptions attach individually, so startup observation counts
  can differ across topics. These samples are counted, not silently discarded.
  Goals wait for recorder readiness. Paused replay avoids losing its first
  samples; any replay loss/count mismatch is a failure, not an allowed margin.

Measured capture/replay results are in [milestone_c.json](../reports/milestone_c.json),
including original action values, independently reconstructed bag outcomes,
comparison deltas, replay hashes/counts/event order and isolation samples.
`healthy.analysis.json`, `cancellation.analysis.json` and their replay JSON/logs
are separate diagnostic artifacts. The full-suite result is also saved to
`milestone_c.tests.json` and `milestone_c.junit.xml`. B's historical result is
preserved; current B regression output uses `milestone_b.regression.*`.

The milestone C colcon suite passed **37 tests: the original 21 plus 16
milestone C cases**, with zero errors, failures or skips. The standalone workflow
also passed. Its retained bags are
`bags/milestone_c_demo_20261031/{healthy,cancellation}`. Measured counts were:

| Capture | Joints | Pose | Atomic state | Task events | Clock | Reconstructed result |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Healthy three-target run | 47 | 48 | 47 | 12 | 48 | Three successes; 4.934, 4.607, 4.659 mm error |
| Cancellation during motion | 6 | 6 | 6 | 5 | 6 | Canceled at 226.094 mm error after 0.060 simulation seconds |

Both replay runs matched every recorded count, content digest and event order.
Outcome, final-error and simulation-duration comparison deltas were zero for
all four goals. The independent installed `bag_analyze` CLI reproduced the
healthy analysis JSON exactly. Live-domain checks observed one clock publisher
and no replay nodes in 150 healthy-replay and 100 cancellation-replay graph
samples; live health stayed good. This evidence covers these short captures,
not arbitrary recorder/playback load or long-duration reliability.

Generated bags are stored under workspace **`bags/`**, with unique test-run
subdirectories or the chosen `--bag-root`. They are excluded by `.gitignore`,
along with `*.db3`, SQLite sidecars and `*.mcap`. Analysis JSON records absolute
bag paths; the bags must remain on disk to repeat offline analysis/replay.

| Milestone C verification | Test |
| --- | --- |
| Healthy three-target capture, reconstruction, exact isolated replay | `test_bags_healthy_record_analysis_and_isolated_replay` |
| Cancellation during motion, recorded outcome and replay order | `test_bags_cancellation_record_analysis_and_replay` |
| Missing/nonbag paths, missing/empty/wrong-type topics, corrupt CDR | Five analyser error-path tests |
| Dropped task event, corrupt final error, incomplete goal | Three mutated-bag tests using real rosbag writers/readers |
| Extra recorded command topic excluded from replay | `test_bags_filter_extra_command_topic` |
| Equal-domain launch rejected; domain range validation | Launch guard plus three parameterized domain tests |
| Explicit timeout and active-reset event contracts | `test_bags_timeout_and_active_reset_event_contract` |

Run the complete suite with the colcon command above. The recording tests also
launch isolated replay, so they need normal local DDS socket access. Do not run
several test/workflow instances in the same pair of domains concurrently.

## Milestone D: fault boundaries and independent monitoring

The task server deliberately consumes **raw** `/testbench/simulation_state`.
It does not consume affected observations or fault settings. The independent
monitor subscribes **only** to `/testbench/observed/state`, `/testbench/task_intent`
and `/clock`. Its core has no ROS simulator/model/fault dependencies. A graph
assertion tests these input boundaries. Raw state topics remain ground truth;
affected joint/pose topics are separate and never overwrite raw publications.

Consequently a raw-controlled task may succeed while the observation monitor
reports an anomaly. This demonstrates monitoring, not closed-loop robustness
to corrupted feedback. `TaskIntent` contains a target, tolerance, generation,
goal ID and active flag, with **no current raw pose, outcome or fault label**.

### Fault configuration and exact semantics

All faults start disabled. The service replaces the complete configuration;
omitted members take the message defaults. Configuration is applied atomically
in the boundary's single-threaded executor. Each successful replacement resets
drop phases and freeze snapshots, even if a flag remains enabled. Example, in
a sourced live terminal:

```bash
ros2 service call /testbench/configure_faults reliability_interfaces/srv/ConfigureFaults \
  '{configuration: {drop_every_n: 3, freeze: false, stop_publication: false,
                    command_delay_seconds: 0.5, queue_capacity: 8, seed: 42}}'
ros2 service call /testbench/configure_faults reliability_interfaces/srv/ConfigureFaults \
  '{configuration: {freeze: true}}'
ros2 service call /testbench/configure_faults reliability_interfaces/srv/ConfigureFaults \
  '{configuration: {stop_publication: true}}'
# Disable everything (also cancels targets still waiting in the delay queue):
ros2 service call /testbench/configure_faults reliability_interfaces/srv/ConfigureFaults '{}'
ros2 service call /testbench/observation_health reliability_interfaces/srv/MonitorStatus '{}'
ros2 topic echo /testbench/diagnostics
```

| Fault / setting | Definition and validation |
| --- | --- |
| `drop_every_n` | 0 disables; 1–1000 suppresses every Nth input on each observation stream. Each configuration restarts the phase at 1. N=1 suppresses all. |
| `freeze` | Retains the last raw values at activation (or the first input if none was received). Position, quaternion, joints and velocities stay fixed while source sequence, generation and simulation/header timestamps advance. |
| `stop_publication` | Suppresses all three affected observation topics; raw topics, clock, intent and control remain active. |
| `command_delay_seconds` | Fixed delay in simulation seconds, finite within [0, 2]. No random jitter. |
| `queue_capacity` | 1–64 targets, including an in-flight target; default 8. Newest target rejected explicitly on overflow. |
| `seed` | Signed 64-bit reproducibility metadata; default 7. These fixed faults use no random draws, so changing seed does not alter them. |

Each affected-state source sequence counts inputs received at the boundary,
including suppressed ones, and restarts at a new simulation generation. Fault
reconfiguration restarts the drop phase but **not** the source sequence. Separate
auxiliary streams have their own phases. Sequence gaps identify missing affected
samples, including suppression/downstream loss; they do not count losses that
occurred before the boundary received a raw sample. Raw-input QoS is reliable.

The command boundary is between the task server and simulator service. Accepted
targets enter FIFO order with a fixed due time. There is one in-flight target;
a later target cannot overtake it. Due times never silently change. Waiting
targets exceeding **2.10 simulation seconds** of residence are rejected with
an `EXPIRED` event instead of being forwarded. This is separate from the 2 s
maximum configured delay. The expiry guard is implemented; overload-driven
expiry has not been exercised by the short local profile. Native service and
OS scheduling latency is measured separately; this is not a real-time actuation
deadline guarantee. Delayed command application is quantized by the 50 Hz raw
stream and native service scheduling.

HOLD commands bypass delay, purge queued targets, and use a higher sequence at
the simulator. Cancellation/timeout results wait for HOLD acknowledgement.
Reset purges first and changes generation. Any already-forwarded request is
fenced by simulator sequence/generation checks; an applied command cannot be
retroactively undone, so HOLD/restoration handles it. Reconfiguration cancels
targets still waiting in the queue; it leaves an already-forwarded request to
complete. The public reset also restores default fault configuration, freeze
caches and phase counters. The tests wait beyond original due times to verify
canceled/timed-out/reset targets do not execute later.

Task timeout and action elapsed simulation time now start at the accepted
goal's latest raw-state sample, **including queue wait**, rather than waiting
for command acknowledgement. This allows a delayed command to time out before
application. The same timestamp convention feeds results and task events. It
includes up to one raw publication period of sampling alignment; zero-delay
reaching, cancellation and the original 5 mm criterion remain verified.

`FaultEvent` records old/new configuration, seed, revision and explicit activated/
deactivated fields. `CommandEvent` records goal/sequence, target, operation,
enqueue/due/application simulation times and QUEUED/FORWARDED/APPLIED/PURGED/
REJECTED/EXPIRED events. These are evidence for the test orchestrator and offline
analysis, never inputs to the independent monitor.

### Monitor thresholds, evidence and recovery

The YAML exposes four startup-validated positive monitor parameters:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `freshness_seconds` | 0.15 steady seconds | No valid affected observation within this interval |
| `startup_grace_seconds` | 0.30 steady seconds | Initial grace if no observation has ever arrived |
| `progress_window_seconds` | 0.20 simulation seconds | Active target outside tolerance with no significant movement/improvement |
| `movement_threshold_metres` | 0.001 m | Minimum cumulative displacement or error improvement to restart the progress window |

The watchdog ticks every 10 ms using a steady clock. Once any observation arrives,
freshness applies immediately; startup grace is not a blanket suppression of
later missing data. The local regression bound for missing-data detection is
**0.35 steady seconds**, including timer/DDS/scheduling margin. Progress evidence
uses a 0.20 s window, verified within **0.26 simulation seconds** of its reference
sample. It is evaluated on received affected observations, not on fault settings.

| Reason code | Evidence / recovery |
| --- | --- |
| `STALE_OBSERVATIONS` | Steady receipt age exceeds freshness, or startup grace expires with no input. Cleared by a valid observation, publishing `OBSERVATIONS_RECOVERED`. |
| `NO_PROGRESS` | Active intent for the same generation, target outside tolerance, and both displacement and error reduction below 1 mm for the simulation window. Movement/in-tolerance observation emits `PROGRESS_RECOVERED`. |
| `NO_PROGRESS_CLEARED` | Intent ended or generation changed; diagnosis no longer applies. This is not proof that a sensor recovered. |
| `OBSERVATION_GAP` | Source sequence skipped within one generation; event contains exact missing count. A pulse, not a latched root-cause diagnosis. |
| `INVALID_OBSERVATION` | Nonfinite position/joints/simulation time; invalid input does not refresh the watchdog. Valid input clears it with `OBSERVATIONS_RECOVERED`. |
| `SEQUENCE_ERROR` | Nonincreasing sequence within a generation; old generations are ignored. |

Diagnostics carry simulation stamp, monitor session/sequence, goal/generation,
observation sequence, steady age, window, displacement, distance and evidence.
`MonitorStatus.ready` means at least one valid observation has arrived;
`active_reasons` identifies current latched anomalies. No NO_PROGRESS alarm is
raised for idle stationary operation or a target already within tolerance.
Legitimate motion slower than the configured movement/window threshold can
trigger NO_PROGRESS; configure thresholds for the task's intended speed.

Fresh timestamps cannot prove values are changing. Conversely, a NO_PROGRESS
result does **not** prove a sensor freeze: queued commands, stalled motion or
other causes can produce the same observation. The monitor says this explicitly.
It does not detect wrong-direction motion if substantial displacement continues.

If simulation pauses and publication stops, steady freshness still detects absent
communication even though ROS time is stationary; it cannot infer whether the
pause was intentional. If publication continues at unchanged simulation time,
freshness stays satisfied and the simulation progress window stops advancing.
Reset's new generation clears the sequence/progress baseline. Pause behavior is
tested with a virtual steady clock; a suspended OS simulator process remains
unverified. Raw-task infrastructure watchdogs are separate from observation health.

### Fault capture, offline analysis and fresh-monitor replay

After the setup/build/source commands above, with no other manual launch running:

```bash
"$TESTBENCH_PYTHON" -m reliability_testbench.fault_demo \
  --bag-root "$PWD/bags/manual_d_run_01" --reports "$PWD/reports" --replay-domain 88
```

Choose an unused bag root. This short run records healthy motion/stationary
operation, missing observations and recovery, frozen observations during motion
and recovery, delayed commands, an expected queued-command timeout, and healthy
operation after faults are disabled. The timeout is an **ABORTED robot task**
and a **passed scenario** because the expected failure/purge was observed.
Other task outcomes and diagnostic expectations are reported separately.

The D recorder extends C's five topics with affected state/joints/pose, task
intent, command timing, fault events and live diagnostics (12 topics total).
It waits for every subscription and active-recorder service readiness, then
uses a committed-message tail barrier before clean shutdown. A healthy-only
capture may contain zero diagnostics; the topic must still exist. Bags stay
under ignored `bags/`; raw ground truth and affected streams are both retained.

Analyze or replay a retained D bag independently:

```bash
ros2 run robot_reliability_testbench fault_bag_analyze \
  bags/manual_d_run_01/faults --output reports/manual_d.analysis.json
ros2 launch robot_reliability_testbench fault_replay.launch.py \
  bag:="$PWD/bags/manual_d_run_01/faults" output:="$PWD/reports/manual_d.replay.json" \
  live_domain:=87 replay_domain:=88
```

Offline analysis reads/deserializes actual messages with `rosbag2_py`, computes
topic counts/timing/digests, reconstructs tasks, reports command delays and
fault/diagnostic timing. Receive latency includes independent recording/DDS
scheduling. Simulation stamp deltas are reported only within one generation.
Temporal association with a fault event is analyst evidence, not information
given to the monitor or proof of root cause.

The D replay launch starts a **fresh monitor** in the isolated child domain.
Only affected state, task intent and recorded `/clock` are replayed. Raw state,
fault configuration/events, command events and recorded diagnostics are **not
published**. New diagnostics use `/replay/diagnostics` with a new monitor session;
recorded `/testbench/diagnostics` remains separate comparison evidence read from
disk. Input counts/content/order are checked. Publisher/graph checks reject live
simulator/controller/boundary or forbidden publishers. Live-domain clock count
and absence of replay nodes are sampled while the replay runs.

Subscriptions/player services are ready before resume. The fresh monitor's
watchdog is armed on the **first captured affected observation** and stopped at
the captured input horizon, before player teardown. Recorder subscriptions can
attach hundreds of milliseconds apart: the clock/intent prefix before the first
affected observation is an incomplete capture, not a live-monitor startup window.
This avoids a false cold-start stale alarm without changing the live startup
grace or freshness thresholds. A capture containing diagnostics before its first
affected observation is rejected because it lacks the baseline to reproduce them.
Playback is 1×
recorded receive timing, with recorded clock only. Lifecycle reason-code order
and observation-gap sequence/count order are compared in separate channels;
their cross-channel interleaving comes from independent DDS writers and a steady
timer and is not required to match. Exact watchdog timestamps/ages and global
cross-writer ordering are not deterministic. Manual playback pauses, altered
rates and near-threshold scheduling can change steady watchdog outcomes; no
identical wall-clock timeout timing is claimed. C's original replay remains
available for C-format captures and all original tests remain in the suite.

Measured scenario expectations/outcomes, latency, task results, bag analysis and
fresh diagnostic comparisons are saved in [milestone_d.json](../reports/milestone_d.json),
with `milestone_d.analysis.json`, `milestone_d.replay.json`, `milestone_d.junit.xml`
and launch/recorder logs. The requirement mapping is
[milestone_d_test_matrix.md](../docs/milestone_d_test_matrix.md).

The final full colcon run passed **64 tests: all 37 earlier cases plus 27 D
cases**, with zero failures, errors or skips. The separate documented demo also
passed all six scenario expectations. Its retained bag is
`bags/milestone_d_demo_20261031/faults`; measured results were:

| Scenario | Observed evidence | Robot-task result |
| --- | --- | --- |
| Healthy motion and stationary baseline | No alarms | Success, 4.645 mm final error |
| Missing observations | Stale after 0.148 steady seconds from configuration request; gap/recovery on re-enable | No task requested in this scenario |
| Frozen values during motion | NO_PROGRESS at 0.200 s simulation window, 0.219 s wall time from request; progress recovery after disable | Raw-controlled task succeeded, 4.645 mm |
| Delayed command | Actual enqueue-to-application delay 0.600 simulation seconds; NO_PROGRESS then progress recovery | Success after 1.040 simulation seconds including queue wait |
| Queued-command timeout | Target purged; no late forward beyond original due time | Expected ABORTED result at 0.160 simulation seconds, 0.190 wall seconds |
| Faults disabled, recovery | No alarms | Success, 4.607 mm final error |

The fresh monitor produced **7 diagnostics**, matching all 7 recorded diagnostics
in the declared reason/gap ordering channels. It used a different monitor session
and a separate output topic. The live domain remained at one clock publisher,
with no replay nodes in 1024 graph samples and no active observation-health
alerts afterward. The installed offline CLI reopened the actual bag and
reproduced analysis exactly; all five recorded task outcomes/errors/durations
matched the action-client measurements (maximum error delta 5.56e-17 m,
zero simulation-duration delta, within the declared 1e-9 comparison tolerances).

The 0.148 s missing-data latency is measured from the configuration request;
the watchdog's age itself is measured from the last received valid observation,
so these durations need not equal the 0.150 s freshness setting. Progress latency
is measured from its observed reference sample, with wall latency reported
separately. These are local short-run measurements, not hard real-time guarantees.

## Limitations and remaining milestones

Static position IK plus upstream actuators is not collision-aware trajectory
planning. There are no obstacles or gripper. Cross-host DDS, arbitrary executor
replacements, process-restart recovery and
stalled-process watchdog behavior remain unverified. The global `/clock`
publisher requires an isolated ROS domain without another simulator/clock.

SQLite3/local reliable playback is verified; MCAP, best-effort/lossy links, high-rate or long
bags, cross-host replay, external domain bridges and interrupted-recording
recovery remain unverified. Overload-driven queue expiry and arbitrary in-flight
transport failure recovery have not been exercised. Hosted GitHub execution and
the 30-minute endurance profile remain unverified. Milestone F is outside this
implementation. No long endurance test has been run.

During E verification, one container run exposed a native SQLite recorder
`database is locked` failure while the live persistence barrier was reading the
bag. Automated C/D recording now uses rosbag2's `resilient` WAL profile, and live
SQLite probes explicitly close their connections (a connection context manager
alone only completes a transaction). WAL permits concurrent readers without
blocking normal writes. The regression verifies the stored WAL mode and database
integrity, then still checks actual message counts, task errors and independent
replay. See the [Jazzy SQLite configuration documentation](https://github.com/ros2/rosbag2/blob/jazzy/rosbag2_storage_sqlite3/README.md).
