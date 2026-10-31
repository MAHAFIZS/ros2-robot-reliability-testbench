# Milestone D requirements, tests and evidence

The earlier 37 A/B/C cases remain. Run all tests using the Docker command in the
README or the native colcon command in [operations](operations.md).
`reports/milestone_d.tests.json` and `milestone_d.junit.xml` record actual outcomes.
Fault cases pass on their declared diagnostic/termination expectations, not by
relabeling a failed robot task as successful. Default reach tolerance is 5 mm.

| Requirement | Tests | Evidence |
| --- | --- | --- |
| Raw/affected separation; monitor sees no truth/fault labels | `test_fault_healthy_motion_and_stationary` graph assertions | Exactly affected state, intent, clock subscribed by monitor; controller subscribes raw |
| Healthy motion and stationary observations | `test_monitor_healthy_stationary_and_motion`, `test_fault_healthy_motion_and_stationary` | No diagnostic alarms; raw action succeeds |
| Deterministic Nth-message drops and disable recovery | `test_fault_drop_repeatability_and_recovery` | Same-generation retained offsets exactly `[1,2,4,5,7,8,10,11]` for N=3, twice per run |
| Frozen values, advancing stamps, no stationary false alarm | `test_fault_freeze_during_motion_but_not_stationary`, `test_monitor_fresh_frozen_values_report_only_no_progress` | Fresh messages, raw motion, NO_PROGRESS within window; PROGRESS_RECOVERED after disable |
| Stop observations; latency and recovery | `test_fault_missing_latency_and_recovery` | Raw stream continues; stale within 0.35 steady seconds; observation recovery |
| Fixed delay and gap-plus-delay combination | Two `test_fault_command_delay_and_drop_combination` cases | Command application ≥ configured 0.50 s and ≤0.58 s; NO_PROGRESS then recovery, gaps when configured |
| Invalid typed fault requests preserve configuration | Seven `test_fault_invalid_configuration_rejected` cases | Negative/NaN/infinite/oversized delay, oversized N, zero/oversized capacity rejected |
| Cancel/timeout/reset purge pending targets | Three `test_fault_pending_commands_never_execute_after_termination` cases | CANCELED or ABORTED result; PURGED event; no late target forward/application beyond original due time |
| Reset disables faults and restores state | Reset case above plus original reset/initial-state tests | Configuration reset, affected observations healthy; old generation cannot execute |
| FIFO, explicit overflow, disable purges waiting command | `test_fault_queue_fifo_overflow_and_disable_purge` | Two forwards in sequence order; newest rejected; disabled pending request never forwards |
| No freeze root-cause claim | `test_monitor_fresh_frozen_values_report_only_no_progress` | Evidence explicitly says freeze/delay/stalled motion cannot be distinguished |
| Source sequence gaps, invalid values, generations | `test_monitor_gap_and_invalid_values`, `test_monitor_startup_grace_and_generation` | Exact gap count; invalid diagnosis; reset baseline avoids false gap |
| Steady freshness with paused simulation | `test_monitor_pause_uses_steady_watchdog_and_recovers` | Clock fixed at zero; stale at virtual 0.16 s and recovery on input |
| Same-input diagnostic repeatability | `test_monitor_repeatability` | Three identical virtual-clock event sequences |
| Full short fault demo, actual bag analysis | `test_fault_bag_demonstration_and_fresh_monitor_replay` | Six scenarios, actual task outcomes including timeout, 12-topic bag, command/fault timing |
| New monitor diagnostics from replayed observations/intent | Same test | New monitor session and `/replay/diagnostics`; exact input digests and reason/gap ordering; no fault/raw/recorded-diagnostic publishers |
| Recorder discovery prefix does not become a replay outage | `test_fault_replay_long_recorder_discovery_prefix` | Actual bag with 0.60 s clock-only prefix; unchanged 0.30 s live grace, exact fresh diagnostic comparison |
| Existing A/B/C behavior | All 37 prior tests | Original physics/action/service/parameter/record/analysis/isolation tests pass |

An initial repeatability test mixed historical generations with equal source
sequence values. It was corrected to compare only the current generation;
expected retained offsets and tolerances were not relaxed. The initial failed
JUnit is retained as `reports/milestone_d.first_suite.junit.xml`; the final
JUnit and JSON identify the current passing run.

A separate replay check exposed the recorder-discovery prefix: clock messages
were captured before the first affected observation, but the live monitor had
already been running. Cold replay initially treated that incomplete prefix as
missing source data. The fresh monitor now arms its watchdog on its first
affected observation, keeps the same thresholds, and rejects captures whose
diagnostics precede that baseline. No diagnostic comparison was weakened.

Bounded-delay configuration is validated to 2 s, capacity to 64. The extra
2.10 s waiting-residence expiry guard is implemented but overload-driven expiry
is not exercised by these short tests. OS process suspension, arbitrary DDS
failure, long/load tests and hardware validation remain unverified. Docker was
subsequently verified in E; hosted CI remains unverified. See the
[F evidence review](verification.md) for the current status.
