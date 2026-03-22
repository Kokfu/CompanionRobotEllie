#!/bin/bash
set -e

# --- Ensure ROS is sourced even if .bashrc didn't run (desktop shortcut, cron, etc.)
if [ -f /opt/ros/humble/setup.bash ]; then
  source /opt/ros/humble/setup.bash
fi
# If you have a workspace overlay, uncomment:
# [ -f ~/turtlebot3_ws/install/setup.bash ] && source ~/turtlebot3_ws/install/setup.bash

# --- Env
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-30}"
# If you rely on these and they’re not already in ~/.bashrc, uncomment:
# export TURTLEBOT3_MODEL=burger
# export LDS_MODEL=LDS-01

# --- Preflight checks (friendlier errors)
for cmd in tmux ros2 python3; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing: $cmd"; exit 1; }
done

SESSION=robot

# If already running, just attach
if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach -t "$SESSION"
fi

# Window 1: Audio bridge
tmux new-session -d -s "$SESSION" -n audio \
  "python3 /home/ubuntu/testaudio/audio_bridge.py --ros-args -p mic_device:=plughw:1,0 -p spk_device:=default"

# Window 2: Servo driver
tmux new-window -t "$SESSION" -n servo \
  "python3 /home/ubuntu/pan_tilt_ros_onefile.py --mode driver"

# Window 3: STT/TTS bridge -> Remote PC
#tmux new-window -t "$SESSION" -n stt \
  #"python3 /home/ubuntu/stt_tts_bridge.py"

# Window 4: TurtleBot3 bringup
tmux new-window -t "$SESSION" -n bringup \
  "ros2 launch turtlebot3_bringup robot.launch.py"

# Window 5: lib camera (add device params if you need a specific camera)
tmux new-window -t "$SESSION" -n camera \
  "ros2 run camera_ros camera_node --ros-args --params-file camera_params.yaml"

# Window 5: v4l2 camera (add device params if you need a specific camera)
#tmux new-window -t "$SESSION" -n camera \
#'ros2 run v4l2_camera v4l2_camera_node --ros-args \
  #-p video_device:=/dev/video0 \
  #-p io_method:=userptr \
  #-p buffer_queue_size:=8 \
  #-p pixel_format:=YUYV \
  #-p output_encoding:=rgb8 \
  #-p image_size:="[640, 480]" \
  #-p time_per_frame:="[1, 30]"'

# Window 6: rosbridge server (WebSocket)
tmux new-window -t "$SESSION" -n rosbridge \
  "ros2 launch rosbridge_server rosbridge_websocket_launch.xml"

# Start on the 'audio' window
exec tmux attach -t "$SESSION"

