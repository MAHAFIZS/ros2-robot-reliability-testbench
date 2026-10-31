# GitHub review preparation

Reaching passed; **overall 30-minute endurance acceptance failed observation
freshness**. All 4,303 tasks succeeded within 5 mm over 1800.0097 wall seconds,
but a 232.241 ms runner receive interval exceeded the unchanged 150 ms limit.
The original failed reports and thresholds remain intact. See the
[endurance review](endurance_30m_review.md) and
[compact measured report](../reports/endurance_30m_investigation.json).

Six later bounded experiments reproduced a 324.675 ms delay only at the runner
for the matched observation sequence, with resource sampling disabled. Source,
boundary and independent monitor intervals remained near 20 ms. This localizes
that event to the runner's downstream delivery/readiness/execution path; it does
**not** identify DDS or executor root cause or establish the cause of either the
232 ms endurance event or earlier 354 ms event. No speculative runtime fix was
made. See [timing evidence](receive_gap_timing_results.md).

## Intended publication

- Source: `src/` (both ROS packages, tests, launch, YAML and pinned Panda assets).
- Build/automation: `Dockerfile`, `docker/`, `requirements.txt`, `scripts/`,
  `.github/workflows/regression.yml`, `.dockerignore`, `.gitignore`, `pytest.ini`.
- Documentation/attribution: `README.md`, `docs/`, `LICENSE`, `NOTICE`,
  `THIRD_PARTY_NOTICES.md`.
- Concise evidence: Git-eligible `reports/` JSON, HTML, JUnit and the retained
  anomaly log `milestone_f.pause_launch.txt`. Failed results are intentional.
- Relative convenience symlinks: `models`, `reliability_testbench`, `tests`.
  Their targets are inside `src/`; preserve them as symlinks.

The required pinned asset subset occupies approximately 33 MB; its largest file
is under 4 MB. These are source assets, not generated output. Their checksums,
license and upstream provenance are retained. Do not blanket-ignore `.obj` files.

`artifacts/`, bags/databases, raw JSONL/NDJSON traces, timing output directories,
30-minute per-task originals, environments, credentials, caches, build/install/log
and distribution outputs stay outside Git and the Docker build context.
Original evidence remains locally under `artifacts/`; compact reports retain
measurements and original hashes. Do not delete local evidence to tidy Git.
Historical reports intentionally retain original paths, process/host metadata and
source fingerprints. Inspect these for personal information before public release;
this preparation does not rewrite historical evidence.

## Instrumentation state

Normal runs and CI default to **timing off / resource sampling on**. The runner
records both flags in configuration. `--timing` opts in; standalone node tracing
requires `TESTBENCH_TIMING_DIR` (unset it for normal operation). Bounded queues and
asynchronous writers retain over-limit gaps without flushing in callbacks.
`--disable-resource-sampling` is diagnostic only and retains failing resource
coverage checks. See [exact tracing commands](receive_gap_instrumentation.md). No new
experiment or endurance workload was run during publication preparation.

## Licensing and CI review

The root Apache-2.0 license now matches both package manifests. Root notices and
[third-party notices](../THIRD_PARTY_NOTICES.md) retain the pinned asset attribution
and explain the separately attributed local controller reference. **Maintainer
confirmation of ownership or redistribution permission for that reference remains
necessary before public release**; no independent license was found in that local
reference. A root license alone does not establish those rights.

CI uses pinned checkout/upload actions, read-only repository permissions,
non-persisted checkout credentials, a 20-minute job timeout, bounded container
checks, failure propagation, always-collected artifacts and container cleanup.
It builds without host environments/build mounts, GPU or privileged access.
The short smoke workload and intentionally failing acceptance control remain
part of CI. Static review and focused local checks are recorded in
[publication review](../reports/publication_review.json).
**Hosted CI remains unverified:** there is no configured remote or existing HEAD.
Do not describe a YAML file or local execution as a successful hosted run.

## First commit and push (manual)

Resolve the rights/metadata review above first. Create an empty repository you
choose on GitHub, replace `OWNER/REPO`, then run these commands yourself. No remote,
commit, push or publication was performed during preparation.

```bash
git add -- .gitignore .dockerignore .github Dockerfile LICENSE NOTICE THIRD_PARTY_NOTICES.md README.md requirements.txt pytest.ini docker docs scripts src reports models reliability_testbench tests
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "Add ROS 2 robot reliability testbench and verification evidence"
git branch -M main
git remote add origin https://github.com/OWNER/REPO.git
git push -u origin main
```

Inspect GitHub → Actions → **Jazzy container regression** for the pushed commit;
download `jazzy-reports-and-logs` even on failure. Verify the tested SHA, JUnit,
healthy acceptance and expected negative-control exit status before claiming
hosted CI passed. [Manual dispatch and CLI inspection commands](verification.md#hosted-ci-and-publication)
are also provided. Freshness failures must remain failures, even when reaching
passes. Unresolved timing localization and RSS-growth interpretation remain
limitations, not reasons to weaken acceptance checks.
