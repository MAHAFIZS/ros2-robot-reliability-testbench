# Final verification and evidence review

**Later follow-up:** a user-executed 30-minute run completed but failed observation
freshness acceptance. See [the endurance review](endurance_30m_review.md). The
inventory and unverified-endurance statements below describe the earlier F review
time; the original F report remains unchanged. Current publication preparation,
licensing review and commands are in [publication.md](publication.md).

This review preserves historical reports and distinguishes executed evidence from
implemented capability. Machine-readable review: [milestone_f.json](../reports/milestone_f.json).
The implementation and acceptance thresholds are unchanged by milestone F.

## Counts and measurements

| Milestone evidence | Cumulative tests | What was actually checked |
| --- | ---: | --- |
| [A JUnit](../reports/milestone_a.junit.xml) | 4 passed | Headless model/physics checks; separate reaching demonstration |
| [B JUnit](../reports/milestone_b.junit.xml) | 21 passed | Packaging, action lifecycle, services, parameters and reset |
| [C JUnit](../reports/milestone_c.junit.xml) | 37 passed | Actual bag analysis, malformed data, recording and isolated replay |
| [D JUnit](../reports/milestone_d.junit.xml) | 64 passed | Deterministic faults, independent diagnostics, command safety and fresh-monitor replay |
| [E JUnit](../reports/milestone_e.junit.xml) | 85 passed, 0 skipped | All earlier cases plus acceptance/report/resource/cleanup/storage checks in Docker |

These are successive suites, not 211 independent tests. The E suite adds 20
endurance/report cases and one bag regression to D's 64. Some cases are
parameterized. Historical failed JUnit files are explicitly named and retained.

The final E healthy workload completed 34/34 targets: maximum final error
0.004914287793266527 m; 18.008554443 wall seconds and 18.040000000 simulation
seconds; 902 affected observations; zero missing sequences and diagnostic events;
maximum steady receive interval 0.023499892 s. The negative control returned 1
for an impossible minimum-task requirement, while the check wrapper returned 0.
Fault scenarios pass on their expected diagnostics/termination, not on pretending
that every robot task succeeded; the D queued-timeout task really failed.

D's six scenario expectations passed. Missing-data detection was 0.148089610 wall
seconds **from the configuration request**, not from the last observation (hence
it can be below the 0.15 s freshness threshold). Frozen-motion NO_PROGRESS used
a 0.2000 simulation-second window; fixed command delay measured 0.6000 simulation
seconds. Seven fresh diagnostic events matched the recorded lifecycle/gap ordering
in a separate monitor session/domain. Wall timing and independent cross-topic
interleaving are not required to match.

CPU/RSS scope is the launch process and four ROS descendants, excluding runner,
kernel and Docker daemon. E's healthy run peak process RSS was 295.3945 MiB.
Positive RSS endpoint changes are reported, not labeled leaks or proof of their
absence. Review [the full short report](../reports/milestone_e.short.json).

F re-executed the [documented walkthrough](demo.md), not the entire regression:
three healthy reaches and six fault scenarios passed, the separate analysis CLI
matched the workflow's actual-bag analysis exactly, and the additional fresh
replay generated seven diagnostics with matching signatures. Its fresh short
run reached 36/36 targets (maximum 4.9195 mm; 18.0093 wall s / 18.0400 simulation
s; 902 observations; no missing sequences or diagnostics). See
[F JSON](../reports/milestone_f.json) and [fresh HTML](../reports/milestone_f.short.html).
The runtime/build-input SHA-256 matches E's validated image. F did not rerun the
30-minute profile or claim a new 85-case suite execution.

## Endurance inventory

No 1800-second/30-minute result was found in `reports/` or the local `artifacts/`
tree. Docker's stopped/running `testbench` container inventory was also checked:
only the F demo container existed; no unexported 30-minute container was found.
Initial review found six actual `endurance.json` files: four 18-second runs
and two eight-second negative controls. Three 18-second runs passed; one failed
as described below. The F walkthrough added one passing 18-second run, bringing
the saved total to seven (five short runs, two negative controls).
Root `milestone_e.*.json` and `milestone_f.short.json` files are exported copies,
not extra independent executions. Other bag/recording tests are not endurance runs.
The 30-minute profile remains **unverified** and was not executed for this
documentation-only milestone. Its exact command remains in
[operations](operations.md#milestone-e-container-ci-and-healthy-endurance).

## The 354 ms anomaly

Source: [failed healthy report](../reports/milestone_e.observation_gap.json),
the run's saved launch/stdout logs and four node logs under
`artifacts/verified/reports/`. A portable copy of the timestamped lifecycle log
is [pause_launch.txt](../reports/milestone_f.pause_launch.txt).

| Available evidence | Supported conclusion | What it cannot establish |
| --- | --- | --- |
| Runner maximum steady observation receive interval **0.353750931 s** | Its affected-state callback saw a freshness interruption exceeding the unchanged **0.15 s** bound | The raw simulator publish interval; the metric is callback receipt time |
| Monitor emitted STALE_OBSERVATIONS then OBSERVATIONS_RECOVERED | A second subscriber/process also observed stale data and recovery | Whether both subscribers were starved, DDS delivery stalled, the boundary stalled, or the simulator stopped producing |
| Diagnostic source sequence **148 → 149**, simulation clock **2.94 → 2.96 s** | Consecutive boundary observations around recovery; simulation stamps advanced one 20 ms step | Those are simulation clock values, not source publish wall timestamps or monitor receive wall timestamps |
| Maximum observed simulation interval **0.02000000000000668 s**, missing sequence count **0** | No skipped boundary sequence or larger simulation-stamp interval was observed within the measured stream | Zero transport latency; the boundary generates sequence numbers on raw receipt, not at the simulator's publish call |
| 886 observations, **17.7200 sim s / 18.000815232 wall s** | Simulation-time progression as seen by the runner lagged wall time by **0.280815232 s** over this window | Whether the simulator actually paused or observations/clock were delivered or processed late |
| Eighth task: **0.3000 sim s / 0.600519189 wall s** | An action transaction also had about **0.300519189 s** extra wall duration | Exact association with the diagnostic goal: saved endurance task rows lack IDs and start/finish timestamps |
| All four node logs are empty; launch log has startup and clean shutdown only; runner stdout empty | No logged crash, restart or exception explains the gap | Absence of an unlogged stall or scheduling delay |
| No bag or per-message raw publish/receive trace for this workload | Recording delay cannot be measured; rosbag2 was not recording this short run | Attribution to a recorder or source publication pause |

**Conclusion:** this was an affected-observation receive/freshness anomaly. The
earlier E wording “publication pause” is a hypothesis, not proven localization.
The simulator, boundary, middleware and subscriber scheduling remain possible
locations. A stall confined only to the endurance callback is less explanatory
because the independent monitor also raised an alarm, but common starvation or
different delays cannot be excluded. Consecutive simulation stamps do not rule
out a source pause: the simulator advances fixed steps per timer invocation.
Buffered observations can also preserve consecutive stamps after delayed delivery.

Earlier probes observed one NumPy thread and a maximum 1.38 ms IK solve over 40
targets. A later host CPU/memory pressure snapshot was zero. These are not
time-aligned with the gap and cannot rule out a transient compute, scheduling,
middleware or system event during that run. The SQLite locking failure in a
different regression recording was addressed with WAL and explicit reader
closure; there is no evidence tying it to this non-recording workload.

The run correctly failed `continuous_observations` and
`no_unexpected_diagnostics` despite **35/35 successful robot tasks**. Its criteria
and 5 mm tolerance were not relaxed. Later identical-criteria passes do not erase
it. This system does not provide a verified real-time freshness guarantee. An
application relying on fresh feedback should treat this event as a health failure
even when raw-state reaching succeeds. Simulation-time task deadlines and the
3-second infrastructure watchdog do not reject every 354 ms freshness failure.

If further localization is undertaken, capture same-host monotonic timestamps
around simulator publish/tick/control work, boundary receipt/publication, both
subscriber callbacks, diagnostic emission and recorder receipt, retaining
generation/sequence/goal IDs. A source wall gap would then be distinguishable from
later delivery/callback delay. A bag receive timestamp alone is insufficient.
No new tracing system or controller changes were added in F.

## Hosted CI and publication

At review time `git status --short` shows untracked project files; HEAD is unborn,
`git remote -v` is empty, and `gh` is not installed. No existing run can be
associated with this repository. **Hosted CI is unverified.** No remote was
created, commit made, push sent or workflow dispatched during this task.

The [workflow](../.github/workflows/regression.yml) has push, pull-request and
manual triggers, a 20-minute job timeout, container tests and always-uploaded
artifacts. Its local command passed; YAML existence is not hosted execution.

User-operated publication steps (review before executing):

1. Review source/model attribution and the root Apache-2.0 `LICENSE` and notices.
   Confirm rights to the attributed local controller reference as described in
   [third-party notices](../THIRD_PARTY_NOTICES.md). Review intended source and compact report files; leave
   `bags/`, `artifacts/`, `.venv/`, `build/`, `install/`, credentials and logs out.
2. Create a commit and publish to a GitHub repository you choose. Example commands
   below are **instructions only**; replace `OWNER/REPO` and confirm the branch:

   ```bash
   git add -- .dockerignore .github .gitignore Dockerfile LICENSE NOTICE THIRD_PARTY_NOTICES.md README.md docker docs requirements.txt scripts src models reliability_testbench pytest.ini tests reports
   git diff --cached --check
   git diff --cached --stat
   git diff --cached
   git commit -m "Add ROS 2 robot reliability testbench and verification evidence"
   git branch -M main
   git remote add origin https://github.com/OWNER/REPO.git
   git push -u origin main
   ```

3. On GitHub: repository → **Actions** → **Jazzy container regression** → inspect
   the push-triggered run. To run manually, **Run workflow** → branch **main** →
   **Run workflow**. For manual dispatch the workflow must be on the default
   branch and Actions enabled; see [GitHub's instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).
4. Inspect the build and regression/smoke steps and download
   **jazzy-reports-and-logs**. Require a successful run plus `checks.json` success,
   regression exit 0, healthy acceptance pass, and negative-control exit 1.
   Retain the run URL, tested commit SHA and artifacts. A failed freshness check
   remains a failure; do not delete it or relabel a later rerun as the same run.

Optional CLI equivalent after installing/authenticating GitHub CLI yourself:

```bash
gh workflow run regression.yml --repo OWNER/REPO --ref main
gh run list --repo OWNER/REPO --workflow regression.yml --limit 5 --json databaseId,headSha,status,conclusion,url
# Select RUN_ID for the intended commit, rather than assuming the latest run is yours.
gh run watch RUN_ID --repo OWNER/REPO --exit-status
mkdir -p artifacts/hosted-ci
gh run view RUN_ID --repo OWNER/REPO --log > artifacts/hosted-ci/run.log
gh run download RUN_ID --repo OWNER/REPO --name jazzy-reports-and-logs --dir artifacts/hosted-ci
```

Official CLI references: [watch](https://cli.github.com/manual/gh_run_watch),
[view](https://cli.github.com/manual/gh_run_view). These commands were not executed.
Only mark hosted CI verified after an actual successful run and artifact review.

The project is ready for employer review as a bounded SIL portfolio. Publication
still needs deliberate file/license review, a commit/remote and actual hosted CI.
Long endurance and pause localization are verification gaps to disclose, not
prerequisites for honestly presenting the demonstrated short-run capabilities.
