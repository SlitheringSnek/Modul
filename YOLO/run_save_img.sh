#!/bin/bash

# Source profile to get environment variables
source ~/.bashrc

# Load secrets (e.g. ROBOFLOW_API_KEY) explicitly. NOT done via ~/.bashrc above:
# Raspberry Pi OS's default ~/.bashrc returns immediately for non-interactive shells
# (the "case $- in *i*) ;; *) return;; esac" guard near its top), so anything appended
# to the end of ~/.bashrc never runs when this script is invoked non-interactively
# (e.g. by Node-RED's exec node) even though it works fine over an interactive SSH shell.
# ~/.roboflow_env is NOT part of this git repo - create it once per Pi with:
#   echo 'export ROBOFLOW_API_KEY="your_actual_key"' > ~/.roboflow_env
[ -f "$HOME/.roboflow_env" ] && source "$HOME/.roboflow_env"

# Set necessary environment variables
export MVCAM_COMMON_RUNENV=/opt/MVS
export LD_LIBRARY_PATH=/opt/MVS/lib:$LD_LIBRARY_PATH
export PATH=/usr/local/bin:/usr/bin:/bin:$PATH

# Navigate to script directory


# Run Python script
/usr/bin/python3 /home/pi/Desktop/YOLO/main.py
