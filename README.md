# ROS 2 Robot Reliability Testbench

A headless software-in-the-loop testbench for a simulated Panda: can a Cartesian
task complete within tolerance, and can an independent observer detect missing
or unchanging feedback without knowing which fault was injected?

ROS 2 Jazzy nodes execute reaching actions, inject deterministic faults at explicit
boundaries, record task outcomes, and replay observations into a fresh health
monitor. The current local Docker regression passed **91 tests**, including all
85 prior cases and six timing tests. This is a simulation
portfolio project; no physical robot or HIL testing is claimed.

## Architecture and interfaces

| Component | Responsibility | Boundary |
| --- | --- | --- |
| `panda_simulator` | MuJoCo ground truth, 50 Hz publication, `/clock` | Sole owner of simulation state; serial stepping/reset/control callbacks |
| `task_server` | Reach action, validation, timeout, reset and task events | Controller consumes **raw** state; one goal at a time, competing goals rejected |
| `fault_boundary` | Separate affected observations and bounded command FIFO | Drop every Nth message, freeze values, stop observations, delay commands; all off by default |
| `health_monitor` | Freshness, observation gaps and lack of progress | Reads affected state, task intent and clock; no raw state or fault configuration |
| Offline analysis / replay | Deserialize actual bags and reconstruct outcomes | Fresh replay monitor in another ROS domain; recorded diagnostics excluded from its inputs |

All paths below except `/clock` have the `/testbench` prefix.

| ROS interface | Type / purpose |
| --- | --- |
| `/reach` | Custom `Reach` action: Cartesian target; distance/progress feedback; success, final error, simulation duration |
| `/reset`, `/health`, `/observation_health` | Custom `Reset`, `Health`, `MonitorStatus` services; raw system health is distinct from observation health |
| `/configure_faults` | Typed `ConfigureFaults` service; validates full configuration and emits revisioned fault events |
| `/raw/joint_states`, `/raw/ee_pose`, `/simulation_state` | `JointState`, `PoseStamped`, custom `SimulationState`; ground truth |
| `/observed/joint_states`, `/observed/ee_pose`, `/observed/state` | Affected observations; custom state includes source sequence/generation |
| `/task_events`, `/task_intent`, `/command_events`, `/fault_events`, `/diagnostics` | Timestamped custom messages; explicit goal IDs and outcomes, independent of action transport internals |
| `/clock` (global) | Simulator clock live; recorded clock during isolated replay, with one clock publisher per domain |

The Python package uses `ament_python`; the separate interface package uses
`ament_cmake`/rosidl. Defaults are **5 mm** target tolerance and **5 simulation
seconds** task timeout. Tolerance/timeout updates reject nonpositive/nonfinite
values; active goals retain their accepted settings. Cancellation, timeout and
reset purge delayed commands. Parameters and all CLI examples are in the
[operational reference](docs/operations.md#launch-and-client-commands).

## Docker quick start

From the repository root, using Docker and Python 3's standard library:

```bash
python3 scripts/build_image.py
docker run --name testbench-checks --network none robot-reliability:jazzy
mkdir -p artifacts
docker cp testbench-checks:/workspace/reports artifacts/
docker cp testbench-checks:/opt/testbench artifacts/dependencies
docker rm testbench-checks
```

The default command runs regression, an 18-second healthy workload and an expected
failing acceptance control. The wrapper returns nonzero on unexpected failure.
Copy reports even if `docker run` fails. The image needs no host Python/build
mounts, display, GPU, privileged mode or host network. Base digest, direct apt
versions and Python dependencies are pinned; resolved manifests are exported.
Apt repository availability and transitive apt resolution remain rebuild inputs.

## Demonstrations

Healthy three-target action run:

```bash
docker run --rm --network none robot-reliability:jazzy \
  ros2 run robot_reliability_testbench milestone_b
```

Fault detection, recovery, real recording, offline analysis and fresh-monitor replay:

```bash
docker run --name testbench-faults --network none robot-reliability:jazzy \
  ros2 run robot_reliability_testbench milestone_d \
  --bag-root /workspace/bags/portfolio --reports /workspace/reports/portfolio
mkdir -p artifacts
docker cp testbench-faults:/workspace/reports artifacts/
docker cp testbench-faults:/workspace/bags artifacts/
docker rm testbench-faults
```

This includes deliberate observation loss → `STALE_OBSERVATIONS`, frozen values
during motion → `NO_PROGRESS`, recovery, command delay and an expected timeout.
A scenario passes when its declared outcome is observed; a timed-out task remains
a failed robot task. Replay compares fresh diagnostics with recorded evidence,
without feeding fault labels or recorded diagnostics into the fresh monitor.
See the **[four-minute demo guide](docs/demo.md)** for explicit analysis/replay
commands, narration and the HTML report. Generated bags/artifacts are Git-ignored.

## Verified results

| Evidence | Actual result |
| --- | --- |
| [Local Docker suite](reports/milestone_e.junit.xml) | 85/85 passed: 64 prior A–D cases + 21 E cases; no skips |
| [Healthy short run](reports/milestone_e.short.json) | 34/34 reaches; max error **4.9143 mm**; **18.0086 wall s / 18.0400 simulation s**; 902 affected observations, no sequence gaps or diagnostics |
| [Fault demonstration](reports/milestone_d.json) | Six expected scenarios passed; missing-data alarm 0.1481 wall s after request; frozen-motion NO_PROGRESS at 0.2000 simulation s window |
| [Fresh-monitor replay](reports/milestone_d.replay.json) | Seven fresh diagnostic events; matching reason/gap ordering, separate monitor session and ROS domain |
| [Negative acceptance control](reports/milestone_e.negative.json) | Healthy tasks with impossible task-count requirement returned **1** and generated failure reports |
| [F walkthrough](reports/milestone_f.json) | Healthy demo, six fault scenarios, independent analysis and two fresh-monitor replays passed; fresh short run **36/36**, max **4.9195 mm** |
| [Bounded receive-gap comparison](docs/receive_gap_timing_results.md) | Six alternating 60-second runs; 911/911 tasks succeeded. One 324.675 ms runner-specific gap reproduced **with sampling off**; root cause not yet separated between delivery/readiness/executor paths |
| [Hosted CI workflow](.github/workflows/regression.yml) | Implemented; matching container checks passed locally. **No hosted run verified.** |
| [30-minute endurance review](docs/endurance_30m_review.md) | **Full 1800.0097 wall s completed**, 4303/4303 task successes; acceptance **failed** on a 232.241 ms receive gap above 150 ms |

Coverage includes physics/model checks, action lifecycle, services/parameters,
concurrent goals, reset/cancel/timeout safety, deterministic faults, monitoring,
malformed bags, recording, replay isolation and report acceptance. Test counts
are cumulative across milestones, not additive. Browse the
[HTML summary](reports/milestone_e.html), [full E JSON](reports/milestone_e.json),
[requirement-to-test matrix](docs/test_matrix.md) and [final evidence review](docs/verification.md).

An earlier healthy workload **failed** its unchanged freshness criteria on a
**353.751 ms affected-observation receive gap**, despite 35/35 task successes.
The monitor reported stale/recovery. Source publish timestamps were not recorded;
the cause and location of the interruption remain unresolved. Later passes do
not invalidate that failure. [Investigation and implications](docs/verification.md#the-354-ms-anomaly).

## Optional timing instrumentation

Timing tracing is **disabled by default**, including normal demos, endurance and
CI. Resource sampling is **enabled by default**. `endurance --timing` enables
bounded, asynchronous tracing; standalone nodes opt in through
`TESTBENCH_TIMING_DIR`. Unset that variable for ordinary operation. Each runner
JSON records both settings. `--disable-resource-sampling` is a diagnostic
experiment: it retains the full acceptance check and fails resource-coverage
criteria. It is not an accepted replacement endurance profile.
See [instrumentation and reproducibility](docs/receive_gap_instrumentation.md) and
[measured overhead/results](docs/receive_gap_timing_results.md).

## Limits and publication status

This demonstrates **monitoring under faults**, not closed-loop sensor-fault
robustness: the controller reads raw simulator state. NO_PROGRESS does not prove
a sensor freeze. Position-only IK is not collision-aware planning. Watchdogs use
steady wall time; motion/progress use simulation time. Replay does not promise
identical wall timing or cross-topic diagnostic interleaving.

No hardware, HIL, production-readiness or absence-of-memory-leaks claim is made.
CPU/RSS trends cover launch and four ROS nodes over short runs, excluding the
runner/kernel/Docker daemon. A later full 30-minute run failed freshness acceptance;
the receive-gap cause and memory-growth interpretation remain unresolved.
The 30-minute command is documented in the
[operational reference](docs/operations.md#milestone-e-container-ci-and-healthy-endurance).

The project is ready for portfolio review with these caveats. Public release still
requires maintainer confirmation of rights to the attributed local controller
reference and review of historical machine/path metadata. The root
[Apache-2.0 license](LICENSE) matches the package metadata; see
[third-party notices](THIRD_PARTY_NOTICES.md). Hosted CI remains unverified.
Nothing has been committed or pushed. See the [publication checklist and exact
first-push commands](docs/publication.md).

Panda assets retain their [Apache-2.0 license](src/robot_reliability_testbench/models/franka_emika_panda/LICENSE)
and [pinned Menagerie provenance](src/robot_reliability_testbench/models/franka_emika_panda/SOURCE.json).
[Portfolio description, CV bullets and interview notes](docs/portfolio_summary.md).
