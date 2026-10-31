# Third-party notices and provenance

The root [LICENSE](LICENSE) provides Apache License 2.0 for original project code,
consistent with both ROS package manifests. It does not replace third-party
licenses or establish permission for code owned by someone else.

## Vendored Panda assets

| Item | Provenance / retained terms |
| --- | --- |
| Franka Emika Panda MJCF and mesh subset | MuJoCo Menagerie, commit `62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35`, directory `franka_emika_panda` |
| License | [Unchanged upstream Apache-2.0 license](src/robot_reliability_testbench/models/franka_emika_panda/LICENSE) |
| Attribution and derivation | [Upstream README](src/robot_reliability_testbench/models/franka_emika_panda/README.md), including derivation from Franka Emika's URDF description |
| Change history | [Unchanged upstream changelog](src/robot_reliability_testbench/models/franka_emika_panda/CHANGELOG.md) |
| File inventory | [SOURCE.json](src/robot_reliability_testbench/models/franka_emika_panda/SOURCE.json), with per-file SHA-256 values checked on simulator initialization |

Upstream repository: [google-deepmind/mujoco_menagerie](https://github.com/google-deepmind/mujoco_menagerie/tree/62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35/franka_emika_panda).
This is a runtime asset subset, not a claim to redistribute every upstream scene
or documentation image. The upstream README is retained as-is, including links
to files outside this subset. No model or mesh was modified during publication
preparation. The bundled asset license must remain with those files.

## Local controller reference — maintainer confirmation remains

`reliability_testbench/simulation.py` attributes its position-only damped-Jacobian
IK and position-actuator bias-compensation approach to the separate local
`robot-data-pipeline` project, `robotics_dataset/franka.py`. The testbench uses its
own smaller simulation implementation; it imports no code or environment from
that project. Cube pushing, cameras, storage and teleoperation were not included.

The available local reference has no independent project `LICENSE` file or
controller copyright/license header. Ownership or redistribution authorization
was **not independently established by this review**. Before a public push,
the maintainer should confirm that they own or have permission to publish the
adapted controller code under this repository's declared terms. Adding a root
license does not resolve that provenance question. No missing license or author
notice has been invented, and no private reference-project contents are copied
into this repository for publication.

## Installed dependencies and container contents

ROS 2 Jazzy, MuJoCo, NumPy, pytest, psutil and their transitive dependencies are
installed through the pinned base image, apt and pip; their source is not vendored
as original testbench code. They retain their upstream terms and notices.

Version/build inputs:

- [Dockerfile](Dockerfile): digest-pinned ROS Jazzy base.
- [Direct apt version lock](docker/apt-packages.lock).
- [Python requirements](requirements.txt), including pinned Python transitives.
- [Measured Python manifest](reports/milestone_e.python-versions.txt) and
  [measured apt manifest](reports/milestone_e.apt-versions.txt): historical E image.
- Every newly built image writes fresh manifests to `/opt/testbench/`; do not
  assume a historical manifest identifies a later image.

Installed wheel license directories and Debian `/usr/share/doc/*/copyright`
remain subject to upstream distribution terms. This file is an attribution and
provenance index, not an exhaustive license inventory for every image package.
The root LICENSE, NOTICE and this file are also copied into `/opt/testbench/` in
new builds. No prebuilt image is published automatically.
