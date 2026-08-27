#!/bin/bash

# Source profile to get environment variables
source ~/.bashrc

# Set necessary environment variables
export MVCAM_COMMON_RUNENV=/opt/MVS
export LD_LIBRARY_PATH=/opt/MVS/lib:$LD_LIBRARY_PATH
export PATH=/usr/local/bin:/usr/bin:/bin:$PATH

# Navigate to script directory


# Run Python script
/usr/bin/python3 /home/pi/Desktop/YOLO/main.py
