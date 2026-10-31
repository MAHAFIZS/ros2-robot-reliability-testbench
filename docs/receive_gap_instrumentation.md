# Bounded observation timing investigation

Executed results: [six-run investigation](receive_gap_timing_results.md),
[JSON](../reports/receive_gap_timing.json), [HTML](../reports/receive_gap_timing.html).

The [30-minute review](endurance_30m_review.md) found a 232.241 ms observer receive
interval above the unchanged **150 ms** threshold. The earlier 353.751 ms event
is also retained. Neither aggregate report establishes the source of its delay.
This follow-up changes instrumentation only, not reaching, faults, controller
feedback, cancellation, timeout or acceptance thresholds.

## Timing records and identity

Tracing is opt-in through `endurance --timing`. The runner passes
`TESTBENCH_TIMING_DIR` only to its owned launch tree. No ROS interfaces or topic
QoS are changed and no timing/fault labels become health-monitor inputs.

| Record | Timestamp / identity |
| --- | --- |
| Simulator | Tick callback entry; before/after raw `SimulationState.publish()`; publication counter, generation and exact message simulation stamp |
| Fault boundary | Raw-state callback entry; before/after affected-state publish; generation, boundary observation sequence and exact simulation stamp |
| Runner / monitor | Affected-state callback entry; generation, boundary sequence and exact simulation stamp |
| Runner executor | Before/after each `spin_once()`; intervals between successive calls |
| Resource sampling | Before/after each synchronous `Resources.sample()` call, including startup/final snapshots |

Publication timestamps bracket the Python API call, including its serialization
and middleware enqueue work. They are **not network wire timestamps**. Another
process can begin receipt before the publisher's API call returns.

Simulation stamps identify samples; they do not measure wall timeliness. The
simulator's publication counter is not assumed equal to the boundary sequence.
Analysis first maps generation + exact integer simulation stamp, then verifies
the same boundary sequence at boundary, runner and monitor. Duplicate keys,
sequence mismatches and noncausal stage starts are rejected, not silently joined.
Missing stage records are counted and invalidate complete coverage.

## Clock comparability

Every point uses Python `time.monotonic_ns()` on local Linux, backed by
`clock_gettime(CLOCK_MONOTONIC)`. Processes inside the same local container share
the same kernel clock origin and time namespace. Each trace records the boot ID,
time-namespace identity, clock implementation and resolution. Analysis requires
these to match across all four processes. No UTC or ROS-time subtraction is used
for stage latency. Do not compare monotonic epochs across unrelated hosts,
containers with different time offsets, rebooted systems or replay sessions.

The intervals distinguish source tick/publish scheduling, boundary processing,
and downstream publish-to-callback delay. The latter still combines transport,
middleware deserialization and executor/OS scheduling; it cannot identify those
individually. Runner-vs-monitor entries give independent observer evidence.

## Bounds, flushing and overhead

Callbacks only capture timestamps and enqueue small records with `put_nowait()`;
they do no file I/O or JSON encoding. A writer thread per process owns JSONL
encoding and buffered file output. Shutdown drains outside callbacks with a
five-second bound. Standard-library queue locks and the Python GIL still have
costs; this is low-overhead instrumentation, not zero-overhead tracing.

Each process has a 4096-record normal queue, a 1024-record priority queue and a
200,000 normal-file-record limit. Observer ring buffers retain 12 preceding and
12 following samples for every receive interval **strictly greater than** 150 ms.
A priority start marker is retained immediately; a completed context follows
after 12 later callbacks. End-of-run contexts explicitly report incomplete tails.
The runner also records a trailing freshness violation at the window boundary.

At most 400 disjoint over-threshold intervals fit in a 60-second window. Reserved
priority capacity is sufficient for the start/context pairs at this duration;
overlapping context windows are bounded by the number of post samples. Queue and
record-limit losses are nevertheless counted. Missing metadata/footer, writer
failure, dropped records or incomplete joins invalidate experimental coverage.
Raw files stay under ignored `artifacts/`; bounded analysis is offline.

Footer measurements include enqueue wall time (count, mean/max and logarithmic
nanosecond buckets) and writer-thread CPU time / active wall time. Enqueue cost
includes gap/context bookkeeping for observers. Caller timestamp preparation and
all end-to-end observer effects are not fully captured by those components.
Writer CPU and enqueue wall costs must not be added as independent CPU costs.
Without a matched uninstrumented workload there is no empirical total slowdown
percentage. Results report these limitations rather than claiming no overhead.

## Alternating experiment

```bash
python3 scripts/build_image.py
docker run --name testbench-timing --network none robot-reliability:jazzy \
  python /workspace/scripts/timing_comparison.py --output /workspace/reports/timing-comparison
mkdir -p artifacts/timing-comparison
docker cp testbench-timing:/workspace/reports artifacts/timing-comparison/
# Inspect/export reports before removing the stopped container.
docker rm testbench-timing
```

The script refuses existing run directories and alternates **on/off/on/off/on/off**:
three 60-second runs with the current synchronous sampling and three without
resource sampling. Each uses the same three reachable targets, seed 7, 5 mm task
tolerance, 5 simulation-second task timeout, six-second action wall bound and
150 ms receive limit. Identical seed fixes the target prefix, not the number of
targets completed within wall time. The final six seconds reserve task completion.
Each runner has a 100-second process bound plus bounded termination cleanup.

**All 12 acceptance criteria are evaluated in both configurations.** With no
resource samples, `resources_collected`, `all_nodes_measured` and
`per_process_rss_bound` fail; they are not waived or relabeled passed. Sampling-off
runs are diagnostic experiments, not replacements for the required endurance
profile. Compare observation, task and diagnostic outcomes separately from those
known resource-coverage failures. The comparison script's successful exit means
six complete, analyzable experiments, not six acceptance passes.

Single-run or offline-analysis commands:

```bash
# Inside the sourced container; choose a fresh output directory each time.
python -m reliability_testbench.endurance --duration-seconds 60 --seed 7 --timing --output /workspace/reports/timing-one
python -m reliability_testbench.timing_analysis /workspace/reports/timing-one/timing --output /workspace/reports/timing-one/timing-analysis.json
```

Add `--disable-resource-sampling` for the diagnostic variant. To establish blocking
sampling, require matched source/boundary/monitor activity during the runner gap
and a resource-sampling span that accounts for the delayed runner callback. A
mere overlapping call or aggregate timing difference is not sufficient evidence
of root cause. No control or sampling redesign is justified without those traces.
If no gap occurs, the conclusion is **“not reproduced in short runs,” not “fixed.”**
