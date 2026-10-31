# Portfolio summary

**Later evidence update:** [a full 30-minute run](endurance_30m_review.md) completed
4,303 successful tasks but failed the 150 ms receive-freshness criterion at
232.241 ms. The interview wording below reflects the earlier F snapshot; when
presenting now, describe endurance as executed with failed acceptance, rather
than not executed. Hosted CI remains unverified.

## Project description

ROS 2 Robot Reliability Testbench is a headless Panda software-in-the-loop project
for testing Cartesian task execution and independent observation health. It
combines Jazzy actions/services/parameters, deterministic observation and command
faults, real rosbag2 analysis, isolated fresh-monitor replay and a self-contained
Docker regression environment. The controller uses raw simulator feedback;
fault tests demonstrate monitoring and command lifecycle safety.

## Three evidence-supported CV bullets

- Built a ROS 2 Jazzy/MuJoCo Panda SIL testbench with a custom Reach action,
  validated runtime parameters and reset/cancel/timeout handling; verified a
  Docker healthy workload of **34/34 successful reaches with ≤4.915 mm error**.
  [Measured evidence](../reports/milestone_e.short.json).
- Implemented deterministic observation/command faults and an independent health
  monitor; verified stale-data/NO_PROGRESS detection, recovery and safe queued
  command purging, with **seven fresh replay diagnostics matching recorded
  ordering** in an isolated ROS domain. [Evidence](../reports/milestone_d.json).
- Packaged a headless Docker environment and locally verified **85 regression
  cases**, machine-readable acceptance/JUnit results and HTML reports; implemented
  a GitHub Actions workflow with failure artifacts and timeouts. **Hosted Actions
  execution remains unverified.** [Evidence](../reports/milestone_e.json).

Use “implemented CI workflow and validated its container commands locally,” not
“passing hosted CI.” The 34-task figure is one measured short run, not a claimed
endurance result or a reliability percentage across all executions. A separate
healthy run failed freshness criteria; it is disclosed in the evidence review.

## 60-second interview explanation

“I built a software-only testbench to separate robot task success from the health
of the observations used to assess it. A headless MuJoCo Panda runs behind ROS 2
Jazzy nodes. A Reach action exposes targets, feedback, cancellation and timeouts;
a fault boundary can drop, freeze or stop observations and delay commands. The
health monitor sees only affected observations and task intent, so it can report
staleness or no progress without reading the injected fault settings.

“I recorded explicit task events and used rosbag2 to reconstruct outcomes, then
replayed only observations and intent into a fresh monitor on another ROS domain.
The local Docker suite passed 85 cases, and a short healthy run reached 34 targets
within 5 mm. I also retained a failed run with a 354 ms receive gap. Its cause
cannot be localized from the saved timestamps. The controller uses raw state,
so I claim monitoring under faults, not closed-loop fault robustness. Hosted CI
and 30-minute endurance are still unverified.”

## Five technical interview questions

**1. How do you avoid blocking simulation while an action waits?**

The simulator is a separate process and owns all MuJoCo state. Its stepping,
reset and control callbacks execute serially. The task server uses async futures
with a reentrant action callback group and a single-thread executor, so awaiting
ROS responses does not busy-wait or block state callbacks/timers. Goal admission
reserves a single active slot before acknowledgement; concurrent goals are
rejected. This design avoids state races but is not a real-time guarantee: a
synchronous simulator callback can still take time.
[Source](../src/robot_reliability_testbench/reliability_testbench/task_server.py).

**2. Why two health services, and can the monitor identify a frozen sensor?**

`/testbench/health` checks raw state and task readiness.
`/testbench/observation_health` reports the independent monitor's active reasons.
The monitor never reads simulator internals or fault configuration. It checks
steady-time freshness and, during active motion outside tolerance, movement or
error reduction over a simulation-time window. Healthy stationary operation
does not trigger NO_PROGRESS. Fresh unchanging values cannot distinguish sensor
freeze from command delay or genuinely stalled motion; NO_PROGRESS states that
observation, not a proven root cause.
[Source](../src/robot_reliability_testbench/reliability_testbench/monitor_core.py).

**3. How do cancellation and reset prevent delayed commands from running later?**

The boundary uses a bounded FIFO with validated maximum delay/capacity and explicit
overflow rejection. HOLD/cancel/timeout purges pending targets; reset also changes
generation and disables faults. Simulator commands carry generation and sequence,
so stale commands cannot apply to restored state. Tests wait beyond original due
times and check command events for purging and absence of late application.
These tests do not prove recovery from every arbitrary in-flight DDS failure.
[Tests](../src/robot_reliability_testbench/test/test_faults.py).

**4. How is replay independent, and which timestamps are trustworthy for what?**

The bag has explicit goal/task events rather than relying on action transport
internals. `rosbag2_py` deserializes actual messages; analysis distinguishes bag
receive timestamps, message stamps and recorded task wall/simulation durations.
A fresh monitor runs in a separate domain, receiving only affected state, intent
and clock. Recorded diagnostics remain comparison evidence on a separate path.
Subscriber readiness precedes playback. Reason/lifecycle order and source-gap
order are compared separately; wall timing is not required to match. A simulation
stamp cannot locate a wall-time publication stall, as the 354 ms anomaly shows.
[Replay source](../src/robot_reliability_testbench/reliability_testbench/fault_bags.py).

**5. What makes the Docker/CI evidence credible, and what remains unverified?**

The digest-pinned Jazzy image builds both ROS packages, includes licensed pinned
assets, and creates its own Python environment. The local run used no host Python,
build or install mounts, no GPU/privilege, and no external networking. It passed
85 cases, a short workload, and an acceptance negative control returning 1.
The workflow implements matching checks and always-uploaded artifacts, but no
remote/commit/hosted run exists yet. Resource scope is launch plus four ROS nodes;
short RSS trends do not establish absence of leaks. No 30-minute or hardware test
is verified. [Verification](verification.md).

## Skills to evidence

| Skill | Implemented work | Verified evidence / boundary |
| --- | --- | --- |
| ROS 2 nodes | Separate simulator, task server, fault boundary and independent monitor | [Architecture](../README.md#architecture-and-interfaces), graph/isolation tests |
| Launch files | Normal YAML-configured system; observation-only and fresh-monitor replay | [Launch sources](../src/robot_reliability_testbench/launch), native integration tests |
| Parameters | 5 mm tolerance, timeout, publication rate, initial joints; finite/positive validation | [ROS tests](../src/robot_reliability_testbench/test/test_ros.py) |
| Services | Reset, raw health, observation health, typed fault configuration | Invalid requests/reset behavior covered by ROS/fault tests |
| Actions | Cartesian Reach feedback/results, single-goal policy, cancel and timeout | [B results](../reports/milestone_b.json); all cases retained in E |
| rosbag2 | Actual recording, deserialization, event reconstruction and isolated replay | [C results](../reports/milestone_c.json), [D replay](../reports/milestone_d.replay.json) |
| Fault injection | Fixed Nth-drop, value freeze, stop and bounded command delay | [D test matrix](milestone_d_test_matrix.md); NO_PROGRESS is not a freeze diagnosis |
| SIL | Headless MuJoCo Panda with preserved raw truth | [Model/physics tests](../src/robot_reliability_testbench/test/test_simulation.py); no HIL/hardware |
| Docker | Self-contained build/test/demo, pinned assets and dependencies, process cleanup | [E report](../reports/milestone_e.json); local container execution verified |
| CI | Actions build/regression/smoke, failure propagation, reports/log uploads and timeout | [Workflow](../.github/workflows/regression.yml); **hosted execution unverified** |

Presentation: [four-minute walkthrough](demo.md). Publication and remaining work:
[final evidence review](verification.md#hosted-ci-and-publication).
