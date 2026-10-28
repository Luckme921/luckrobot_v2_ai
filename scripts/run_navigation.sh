#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# ROS-generated setup scripts inspect optional variables without ${var:-}.
set +u
source /opt/ros/humble/setup.bash
set -u
export ROS_DOMAIN_ID=100
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_LOCALHOST_ONLY=0
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"
exec /usr/bin/python3 -u -m edge.navigation.ros_bridge
