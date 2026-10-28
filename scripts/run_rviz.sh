#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/humble/setup.bash
export ROS_DOMAIN_ID=100 RMW_IMPLEMENTATION=rmw_fastrtps_cpp ROS_LOCALHOST_ONLY=0
export QT_QPA_PLATFORM=xcb
exec /opt/ros/humble/lib/rviz2/rviz2 -d "$1"
