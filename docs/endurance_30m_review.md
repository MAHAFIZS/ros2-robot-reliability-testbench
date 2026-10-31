# 30-minute endurance: completed window, failed freshness acceptance

Follow-up to the E/F short-run evidence. **The long test was not rerun for this
review.** The removed container's exit status 1 was reported by the user and is
consistent with the independently recomputed acceptance result.

Original local artifacts, unchanged (local-only paths, intentionally absent from Git):

- JSON: `artifacts/reports/endurance-30m/endurance.json`
- JUnit XML: `artifacts/reports/endurance-30m/endurance.junit.xml`
- HTML: `artifacts/reports/endurance-30m/endurance.html`
- Predeclared acceptance: `artifacts/reports/endurance-30m/acceptance.before_run.json`
- Launch output: `artifacts/reports/endurance-30m/launch.log`
- Timestamped launch log and five per-process logs: `artifacts/reports/ros-logs/`.

These bulky originals remain Git-ignored local artifacts. The compact,
publication-safe [investigation JSON](../reports/endurance_30m_investigation.json)
contains measured summaries, original SHA-256 hashes and limitations; the
[investigation HTML](../reports/endurance_30m_investigation.html) is standalone.
The historical E/F reports were not rewritten.

## Duration and task results

| Measurement | Actual result |
| --- | ---: |
| Required measurement window | 1800.0000 wall seconds |
| Actual measurement window | **1800.009734103 s — full 30 minutes completed** |
| Simulation progression during measurement | 1800.039999971 s |
| Startup/warmup | 1.097885238 wall s |
| Total runner duration including startup/shutdown | 1801.634906877 wall s |
| Task attempts / complete results | 4303 / 4303 |
| Successful / failed / timed-out tasks | **4303 / 0 / 0** |
| Maximum final position error | **0.004921259286 m = 4.921259286 mm**, below 5 mm |
| Maximum task wall duration | 0.536551797 s, below 6 s |
| Maximum task simulation duration | 0.400000000 s, below 5 s |

Every result has status 4 and message `Target reached`; no attempted task lacks
a result. The profile reserves the final six seconds for bounded task completion
and continued observation; it does not start new goals in that interval.

## Why acceptance failed

The JSON, JUnit and embedded HTML JSON agree: **11 of 12 criteria passed**.

| Failed criterion | Predeclared threshold | Measured value |
| --- | --- | --- |
| `continuous_observations` | Maximum steady receive/callback interval ≤0.150000 s | **0.232240658 s (232.241 ms)**, 82.241 ms above the limit |

The other parts of that criterion passed: 90,002 affected observations were
received (minimum 1), with zero missing boundary sequence numbers (required 0).
Maximum simulation-stamp interval was 0.020000000000095497 s. That is a message
simulation-time interval, not evidence of a 20 ms wall-time publish schedule.
Only the maximum wall interval is retained; the number, location and wall time of
over-limit gaps cannot be recovered from this report.

Unexpected diagnostic counts are `{}`; diagnostic examples and fault events are
empty. All task/error/duration criteria, all-node resource coverage, the 512 MiB
per-process RSS bound and absence of reported infrastructure exceptions passed.
The configuration recorded before launch exactly matches the final report.
No tolerance or acceptance threshold was modified.

## Runtime and output completeness

`failures` is empty. All three output formats parse completely and contain the
same outcome. Offline recomputation of all 12 criteria matches the original, and
calling the report writer on a temporary copy returns 1. That check launches no
ROS nodes and does not execute a workload.

The launch logs show startup followed by SIGINT and clean exits for simulator,
task server, boundary and monitor. The runner deliberately sends SIGINT during
cleanup; launch's generic “user interrupted” line does not establish that someone
stopped the run early. The completed window and empty exception list support
normal completion with failed acceptance, not a crash. The five node/runner log
files are empty, so they provide no callback or exception detail. The removed
container's metadata/stdout cannot be recovered beyond the exported files.

## CPU and memory

Each process has 1,770 samples over 1800.012 s: approximately 1.018 s between
samples on average. CPU is process CPU time divided by steady sampling interval.

| Process | RSS start → end / sampled peak (MiB) | RSS change (MiB) | Mean / peak sampled CPU (%) |
| --- | --- | ---: | ---: |
| ros2 launch | 39.840 → 39.840 / 39.840 | 0.000 | 0.00 / 0.00 |
| Simulator | 295.109 → 295.840 / 295.840 | +0.730 | 12.15 / 15.95 |
| Task server | 293.938 → 309.500 / 309.500 | **+15.563** | 22.56 / **334.77** |
| Fault boundary | 73.586 → 73.883 / 73.883 | +0.297 | 40.65 / 48.83 |
| Health monitor | 70.109 → 70.258 / 70.258 | +0.148 | 28.41 / 34.93 |

All sampled RSS peaks stayed below 512 MiB. Task-server endpoint growth corresponds
to about **0.519 MiB/minute**; endpoints alone cannot show whether memory plateaued
or kept growing. Allocation/cache growth, a leak and other causes cannot be
distinguished here. This does not prove either a leak or its absence.

Scope excludes the endurance runner itself, Docker daemon, kernel and unrelated
host processes. No full resource time series or sampling-call durations were
saved, so CPU/RSS cannot be aligned to the receive gap. CPU can exceed 100% for
multithreaded processes; the sampler also uses a short final interval, making
CPU-time quantization a possible source of exaggerated peaks. The 334.77% peak
does not establish sustained high CPU or explain the delay. Between-sample RSS
peaks are not captured.

## Comparison with the earlier 354 ms event

| Evidence | Earlier short run | This 30-minute run |
| --- | ---: | ---: |
| Maximum runner receive interval | 353.751 ms | 232.241 ms |
| Missing boundary sequences | 0 | 0 |
| Independent monitor's received diagnostics | STALE_OBSERVATIONS + OBSERVATIONS_RECOVERED | None |
| Measured wall / simulation progression | 18.000815 / 17.720000 s | 1800.009734 / 1800.040000 s |

Both used the same runtime fingerprint, dependency versions, seed, 150 ms
freshness criterion and 5 mm tolerance. They share an **observed failure category**,
not a proven cause. The earlier run had a monitor alarm and an overall simulation
lag; this run has no received monitor alarm and no net simulation lag.

A runner-specific callback backlog/delay is plausible in the new run. Code review
shows synchronous `Resources.sample()` calls between `rclpy.spin_once()` calls in
the same thread; process enumeration and CPU/RSS reads therefore delay the next
callback. Action-client work, DDS delivery and OS scheduling are other candidates.
No timing of those operations was retained, so none can be named as the cause.
Absence of a received monitor alarm is not independent proof of continuous source
publication or complete diagnostic delivery. Raw source publish timestamps and
a bag of this run are unavailable. Consecutive simulation stamps/sequences can
also survive buffering after a wall-time delay.

**No code defect is established by these artifacts.** No speculative runtime
change was made. The acceptance logic correctly rejected the observed receive
gap, and the original failed result remains a failure.

## Next action

Do not repeat 30 minutes unchanged. First perform a bounded short timing
investigation that retains monotonic publish/receive timestamps at the simulator,
boundary, runner and monitor, plus resource-sampling durations and gap event
sequence/goal IDs. That distinguishes source interruption from delivery or local
callback delay. Keep the 150 ms and 5 mm thresholds. If those traces establish a
blocking code path, fix it and run focused short regression tests before deciding
whether another endurance execution is warranted.

In plain language: **the robot completed all 4,303 tasks over the full half-hour,
but the observer went too long between two processed updates. The program
correctly returned 1 for that failed health requirement, not because reaching
failed or the simulator crashed.**
