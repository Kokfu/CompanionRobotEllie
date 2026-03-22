#!/bin/bash
# Kill the tmux session if it exists
tmux has-session -t robot 2>/dev/null
if [ $? -eq 0 ]; then
    tmux kill-session -t robot
fi

