# Requirement-to-test and evidence index

The current regression has **91 cases**, including parameterized cases: 85 prior
cases plus six timing cases. Counts below are cumulative and must not be summed.
F changed documentation only; the later timing investigation adds optional traces.

| Requirement | Test source / detailed matrix | Executed evidence |
| --- | --- | --- |
| Headless Panda, pinned model assets, reaching ≤5 mm | [simulation tests](../src/robot_reliability_testbench/test/test_simulation.py) | [A: 4 tests](../reports/milestone_a.junit.xml); physics cases also run in E |
| Jazzy packaging, launch, action feedback, cancellation, timeout, concurrent goal policy, reset, health and parameters | [ROS tests](../src/robot_reliability_testbench/test/test_ros.py) | [B: 21 cumulative](../reports/milestone_b.junit.xml) |
| Actual rosbag2 recording/analysis, invalid bags, observation-only isolated replay | [bag tests](../src/robot_reliability_testbench/test/test_bags.py) | [C: 37 cumulative](../reports/milestone_c.junit.xml); WAL concurrency case added in E |
| Raw/affected boundaries, deterministic faults, queue safety, independent monitoring and fresh-monitor replay | [D matrix](milestone_d_test_matrix.md) | [D: 64 cumulative](../reports/milestone_d.junit.xml), [measured fault outcomes](../reports/milestone_d.json) |
| Docker isolation, seeded healthy workloads, acceptance/reporting, CPU/RSS, process cleanup, CI workflow | [E matrix](milestone_e_test_matrix.md) | [E: 85 cumulative](../reports/milestone_e.junit.xml), [measured E JSON](../reports/milestone_e.json) |
| Honest evidence counts, pause investigation, endurance inventory, CI status | [F evidence review](verification.md) | [F review/checks](../reports/milestone_f.json); historical reports kept |
| Reproducible employer demonstration and portfolio claims | [four-minute guide](demo.md), [portfolio summary](portfolio_summary.md) | F executes the documented demos and validates links/command syntax; results in F JSON |
| Bounded cross-process timing, sequence matching, gap context, loss/overhead accounting and unchanged acceptance | [Timing tests](../src/robot_reliability_testbench/test/test_timing.py), [method](receive_gap_instrumentation.md) | [91-case JUnit](../reports/receive_gap_timing.junit.xml), [six alternating 60-second runs](receive_gap_timing_results.md) |

Implemented but unverified: hosted Actions execution. A subsequent full
[30-minute endurance run](endurance_30m_review.md) completed but failed receive
freshness acceptance; the run is executed, not an endurance acceptance pass.
Unresolved: location/cause of the 354 ms observation receive gap. Expected injected
fault outcomes and the negative acceptance control are distinguished from
unexpected failures. No thresholds were weakened for F.
