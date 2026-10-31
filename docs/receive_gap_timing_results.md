# Receive-gap timing: six bounded comparisons

**One receive gap reproduced, without resource sampling. No sampling redesign
is justified by this evidence.** The original 232 ms and 354 ms results and the
150 ms acceptance threshold are unchanged. The 30-minute test was not rerun.

[Machine-readable results](../reports/receive_gap_timing.json) ·
[HTML investigation](../reports/receive_gap_timing.html) ·
[91-case regression JUnit](../reports/receive_gap_timing.junit.xml) ·
[Instrumentation method and commands](receive_gap_instrumentation.md)

## Design and acceptance

The order was on/off/on/off/on/off: three 60-second runs with the existing
synchronous resource sampling and three with resource sampling disabled. All
other configurations and the robot YAML matched exactly: seed 7, the same three
reachable targets, default 5 mm tolerance, 5 simulation-second timeout and 150 ms
receive bound. Actual target prefixes matched across the first 148 tasks of all
six runs. Different task counts reflect wall-time execution, not changed targets.

All 12 acceptance criteria ran unchanged. Sampling-off runs are **diagnostic
experiments**, not replacement endurance profiles: with no resource samples,
`resources_collected`, `all_nodes_measured` and `per_process_rss_bound` fail
explicitly. They are not waived or marked passed. The gap-containing run also
fails `continuous_observations`.

| Run | Sampling | Wall s | Successful tasks | Max runner receive ms | Gaps >150 ms | Acceptance |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 01 | On | 60.0065 | 148/148 | 28.190 | 0 | All criteria passed |
| 02 | Off | 60.0082 | 149/149 | **324.675** | **1** | Freshness + three missing-resource criteria failed |
| 03 | On | 60.0063 | 156/156 | 33.983 | 0 | All criteria passed |
| 04 | Off | 60.0085 | 148/148 | 27.131 | 0 | Three missing-resource criteria failed |
| 05 | On | 60.0074 | 154/154 | 33.305 | 0 | All criteria passed |
| 06 | Off | 60.0078 | 156/156 | 29.547 | 0 | Three missing-resource criteria failed |

All **911 tasks succeeded**, with maximum final error **4.92125 mm**. No unexpected
diagnostic events, missing observation sequences or runtime failures were
recorded. All runs completed the full 60-second window, including the final
six seconds reserved for task completion and observation. These are three runs
per condition, not a statistically established causal comparison or a guarantee
that sampling-on cannot cause another gap.

## The matched gap

The gap in run 02 was between boundary observation sequences **143 and 144**,
generation **1**. Sequence 144 has simulation stamp **2.860000000 s**. The analysis
matched the exact generation/stamp to simulator publication, verified the same
boundary sequence at both observers, and retained **12 preceding and 12 following
samples**. The context window is complete.

| Interval for the adjacent samples | Measured |
| --- | ---: |
| Simulator tick entries | 19.924 ms |
| Raw simulator publication call starts | 19.913 ms |
| Boundary callback entries | 19.767 ms |
| Boundary publication call starts | 19.729 ms |
| Monitor callback entries | 19.712 ms |
| Runner callback entries | **324.675 ms** |

For sequence 144 itself:

- Source publication to boundary callback: **1.206 ms**.
- Boundary processing before publish: **0.195 ms**.
- Boundary publish API call: **0.166 ms**.
- Boundary publication start to monitor callback: **0.901 ms**.
- Boundary publication start to runner callback: **305.946 ms**.
- Runner callback was **305.045 ms** later than the monitor callback for the same
  observation.

During the runner's gap, 34 overlapping `spin_once()` spans were recorded. The
longest was **10.532 ms**, and the longest interval between those spans was
**0.329 ms**. The runner continued spinning; there was no 300 ms synchronous
resource call, no resource sample at all in this run, and no trace-enqueue call
of that duration. Following observations arrived at the runner with decreasing
delay, consistent with buffered catch-up; the monitor received those same
observations promptly.

This establishes a **runner-specific downstream delay after boundary publication**
for this event. Simulator scheduling and boundary processing do not account for
it. The boundary publish API had returned long before the runner callback.
However, publish-to-callback measurements still combine reader-specific DDS
transport/reliability handling, middleware readiness/deserialization and executor
selection/scheduling. The trace does not separate those mechanisms, so no single
root cause or library defect is claimed.

Resource sampling was **not necessary** for this reproduction. In the three
sampling-on runs, the longest measured sampling calls were **3.281, 3.413 and
3.649 ms**, with typical medians near **2.0 ms**. No sampling span explains the
324.675 ms event. Moving sampling to another thread would therefore be a
speculative fix, and was not done.

## Coverage, clock checks and overhead

All **18,006 measured observations** joined completely across simulator, boundary,
runner and monitor. There were **zero mismatched sequences, duplicate keys,
incomplete joins or dropped instrumentation records**. No monitor receive gap
above 150 ms was traced in any of the six measurement windows. Boot ID,
time-namespace identity, clock implementation and resolution matched across
processes. These are local container `CLOCK_MONOTONIC` measurements, not ROS time
or clocks assumed synchronized across hosts.

Each callback enqueues into bounded queues; JSON encoding and buffered file writes
run on dedicated writer threads. Gap context uses bounded rings and a reserved
priority queue. Shutdown drains outside callbacks. The total raw timing data was
about **17.8 MB** across all six runs and remains under ignored
`artifacts/timing-comparison/reports/timing-comparison/`.

Measured enqueue costs and writer CPU over active trace lifetime:

| Process | Mean enqueue cost range (µs/call) | Maximum enqueue cost (µs) | Writer-thread CPU (% of one core) |
| --- | ---: | ---: | ---: |
| Simulator | 38.85–42.50 | 194.41 | 0.98–1.09 |
| Boundary | 37.50–38.78 | 200.11 | 1.05–1.15 |
| Monitor | 44.74–47.81 | 1315.17 | 0.98–1.13 |
| Runner | 29.97–31.95 | 259.92 | 2.34–2.77 |

These are measured overhead components, not proof of zero observer effect. Caller
timestamp preparation and all scheduling effects are not fully included; enqueue
wall time is not interchangeable with writer CPU time. There was no matched
uninstrumented batch, so total incremental end-to-end overhead is unverified.

## Validation and next measurement

The isolated image passed **91 regression cases**: all 85 prior cases plus six
timing tests for exact-threshold behavior, bounded context/tail retention, queue
overflow accounting without callback I/O, record limits, sequence mapping and
unchanged acceptance with sampling disabled. A separate 10-second pilot joined
500 observations completely with no losses before the six-run batch.

The historical 232/354 ms events lacked these traces. The new 324.675 ms event
does not establish that they share a cause; the older 354 ms event also had a
monitor stale/recovery alarm, unlike this reproduction.

**Next measurement:** retain runner wait-set readiness, selected callback/entity
and subscription-take timestamps alongside reader-side DDS arrival/reliability
evidence, using the same generation/stamp/sequence identities. That can distinguish
late reader delivery/readiness from a ready subscription not being selected.
Keep the threshold, control behavior and original failures intact. No 30-minute
rerun, commit or push was performed; no unsupported sampling fix was introduced.
