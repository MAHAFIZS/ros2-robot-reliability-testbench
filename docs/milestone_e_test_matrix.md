# Milestone E requirements and evidence

All original 64 A–D cases remain in the regression invocation. E adds acceptance,
reporting, configuration, reproducibility and real child-process cleanup tests in
`test_endurance.py`. Executed results are in `reports/milestone_e.json`.
The final container suite passed 85/85 cases (64 prior + 20 endurance/report
cases + one concurrent-storage regression). The native bag tests also verify
the WAL-mode fix. Earlier failed measurements are retained in the E report.

| Requirement | Automated check or execution |
| --- | --- |
| Self-contained Jazzy and pinned assets | Docker build compiles both packages; original model hash/physics tests execute inside image; digest-pinned base, Python requirements, dependency manifests |
| No host environments/build trees, GPU or privilege | Container checks with `--network none`, no mounts, no GPU/privileged flags; Docker inspection recorded |
| Preserve A–D behavior | Complete regression suite, including both native rosbag replay domains and fault tests |
| Seeded varied reachable workload | `test_endurance_seeded_targets_repeat_and_do_not_stall`; actual short workload |
| Fixed 30-minute local profile | `test_endurance_long_profile_is_thirty_minutes`; long execution intentionally not run |
| Configuration validation | Five `test_endurance_rejects_invalid_configuration` cases |
| Success, 5 mm errors, gaps, diagnostics, resources and duration acceptance | Ten adverse-data `test_endurance_acceptance_detects_regressions` cases; actual short profile |
| JSON/JUnit/HTML failure agreement and HTML escaping | `test_endurance_failure_reports_agree_and_escape_html` |
| Bounded shutdown including separate sessions | `test_endurance_cleanup_includes_separate_session_child`; launch tree shutdown after both workloads |
| Child failure cannot silently pass | `test_endurance_detects_disappearing_process` uses an actual terminated descendant |
| Concurrent bag persistence readers do not abort recording | `test_bags_concurrent_persistence_checks_use_wal` and D capture assert WAL; native persistence barriers run during recording, full record/analyze/replay tests |
| Actual nonzero acceptance failure | Container negative control: eight-second healthy run with impossible one-million-task requirement; expected exit 1 and specific failed criterion checked |
| CI error propagation, artifacts, timeouts | `container_checks.py` phase exit checks, JUnit/report generation in finally; workflow pipefail, job timeout and always-upload; hosted execution remains separate |
| CPU/RSS trends and provenance | Actual short JSON contains each owned process, endpoint RSS trend, CPU, dependency versions, source fingerprint and honest unborn revision |
| Fault expectations remain separate | Existing D suite and fault reports; healthy endurance treats diagnostics/fault events as unexpected failures |

The short test provides functional and resource samples, not a memory-leak claim.
No 30-minute, hardware or hosted GitHub validation follows from a local short run.
