#!/bin/bash
set -e

SESSION=remote_pc

# Kill the tmux session if it exists
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Stopping tmux session: $SESSION"
  tmux kill-session -t "$SESSION"
else
  echo "No tmux session named $SESSION found."
fi

