#!/bin/bash
set -e

# --- Ensure ROS is sourced
if [ -f /opt/ros/humble/setup.bash ]; then
  source /opt/ros/humble/setup.bash
fi
# If you have workspace overlay
# [ -f ~/turtlebot3_ws/install/setup.bash ] && source ~/turtlebot3_ws/install/setup.bash

# --- Preflight check
for cmd in tmux ros2 python3; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing: $cmd"; exit 1; }
done

SESSION=remote_pc

# If already running, just attach
if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach -t "$SESSION"
fi

# Window 1: Navigation2
tmux new-session -d -s "$SESSION" -n nav2 \
  "ros2 launch turtlebot3_navigation2 navigation2.launch.py use_sim_time:=False map:=/home/kokfu/turtlebot_webui/v3/config/map.yaml"

# Window 2: Flask app (webui)
tmux new-window -t "$SESSION" -n webui \
  "python3 /home/kokfu/turtlebot_webui/v3/app.py"

# Window 3: Voice bridge
tmux new-window -t "$SESSION" -n voice \
  "python3 /home/kokfu/turtlebot_webui/v3/start_voice_bridge.py"

# Attach to the session (starts on nav2 window)
exec tmux attach -t "$SESSION"

