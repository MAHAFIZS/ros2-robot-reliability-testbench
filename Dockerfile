# Ubuntu 24.04 / ROS Jazzy multi-platform manifest, resolved and verified locally.
FROM ros:jazzy-ros-base@sha256:8eed0a4669bbf43ee331878a4c39bd8ebddea8e3312a58b4fae8edb14526b617
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive
COPY docker/apt-packages.lock /tmp/apt-packages.lock
RUN apt-get update && xargs -a /tmp/apt-packages.lock apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
RUN /usr/bin/python3 -m venv --system-site-packages /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /workspace
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY scripts/ scripts/
COPY docker/ docker/
RUN source /opt/ros/jazzy/setup.bash && \
    python -m colcon build --base-paths src \
      --cmake-args -DPython3_EXECUTABLE=/opt/venv/bin/python -DPYTHON_EXECUTABLE=/opt/venv/bin/python \
      2>&1 | tee /workspace/build.log
RUN mkdir -p /opt/testbench && dpkg-query -W > /opt/testbench/dpkg-versions.txt && \
    python -m pip freeze > /opt/testbench/python-versions.txt && \
    cp /workspace/build.log /opt/testbench/build.log
COPY LICENSE NOTICE THIRD_PARTY_NOTICES.md /opt/testbench/
ARG GIT_REVISION=unknown
ARG GIT_DIRTY=unknown
ARG SOURCE_SHA256=unknown
ENV TESTBENCH_GIT_REVISION=$GIT_REVISION TESTBENCH_GIT_DIRTY=$GIT_DIRTY \
    TESTBENCH_SOURCE_SHA256=$SOURCE_SHA256 \
    ROS_DOMAIN_ID=87 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
    ROS_LOG_DIR=/workspace/reports/ros-logs PYTHONUNBUFFERED=1
LABEL org.opencontainers.image.revision=$GIT_REVISION
ENTRYPOINT ["/usr/bin/tini", "--", "/bin/bash", "/workspace/docker/entrypoint.sh"]
CMD ["python", "/workspace/scripts/container_checks.py"]
