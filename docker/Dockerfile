# Reproducible Nav2 benchmark image: ROS 2 Jazzy + Nav2 + Gazebo + the runner.
#
# Build (from the repo root):
#   docker build -f docker/Dockerfile -t nav2-scenario-runner:jazzy-gazebo .
#
# Run the benchmark and emit dashboards into ./out on the host:
#   docker run --rm -v "$PWD/out:/out" nav2-scenario-runner:jazzy-gazebo \
#     bash docker/run_benchmark.sh /out
FROM ros:jazzy-ros-base

ENV DEBIAN_FRONTEND=noninteractive \
    ROS_DISTRO=jazzy

# Nav2, the minimal TurtleBot3 sim (world + params + bringup), Gazebo bridge,
# and Python tooling. nav2-minimal-tb3-sim is Nav2's own demo robot, so the
# benchmark runs without an external robot description.
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3-pip \
      python3-venv \
      git \
      ros-jazzy-navigation2 \
      ros-jazzy-nav2-bringup \
      ros-jazzy-nav2-minimal-tb3-sim \
      ros-jazzy-ros-gz \
      ros-jazzy-rmw-cyclonedds-cpp \
    && rm -rf /var/lib/apt/lists/*

ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    TURTLEBOT3_MODEL=waffle \
    GZ_SIM_RESOURCE_PATH=/opt/ros/jazzy/share

# Install the runner itself (editable, so a mounted source tree stays usable).
WORKDIR /opt/nav2_scenario_runner
COPY . /opt/nav2_scenario_runner
RUN pip install --no-cache-dir --break-system-packages -e .

# Sanity check at build time: the CLI imports and the benchmark scenarios lint.
RUN nav2_scenario_runner --version \
    && nav2_scenario_runner lint examples/benchmark/scenarios/

# Source ROS for every interactive shell.
RUN echo 'source /opt/ros/jazzy/setup.bash' >> /etc/bash.bashrc

ENTRYPOINT ["/bin/bash", "-lc"]
CMD ["nav2_scenario_runner doctor --check-gazebo"]
