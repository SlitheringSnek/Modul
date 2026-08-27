#Uvoz potrbnih knjižnic
import os
import time
import sys
#import paho.mqtt.client as mqtt
import json
from serial.tools import list_ports
from pydobotplus import Dobot, CustomPosition

#Povezava na dobota
available_ports = list_ports.comports()
#print(f'available ports: {[x.device for x in available_ports]}')
port = available_ports[0].device
device = Dobot(port=port)

seconds = 8

# Control the conveyor belt
try:
    while seconds != 0:
        print("Seconds: ", seconds)
        device.conveyor_belt(speed=1, direction=1)
        seconds -= 1
        time.sleep(1)

except KeyboardInterrupt:
    device._set_stepper_motor(speed=0)
    print("Process interrupted manually")

finally:
    device._set_stepper_motor(speed=0)
    device.close()

print("Transport operation finished")
