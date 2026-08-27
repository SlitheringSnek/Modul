#Uvoz potrbnih knjižnic
import os
import time
import sys
#import paho.mqtt.client as mqtt
import json
from serial.tools import list_ports
from pydobotplus import Dobot, CustomPosition
import RPi.GPIO as GPIO


# Set up the GPIO mode and pin
GPIO.setmode(GPIO.BCM)
GPIO.setup(17, GPIO.IN)

def read_gpio_signal(pin):
    # Read the value from the specified GPIO pin
    signal = GPIO.input(pin)
    # Return True if the signal is HIGH, otherwise False
    return signal == GPIO.HIGH


#Povezava na dobota
available_ports = list_ports.comports()
#print(f'available ports: {[x.device for x in available_ports]}')
port = available_ports[0].device
device = Dobot(port=port)

state = True

try:
    while state:
        device.conveyor_belt(speed=1, direction=-1)
        signal = read_gpio_signal(17)
        print("IR signal :", signal)
        if signal == False:
            state = False
            print("Part ready for transport")
            device._set_stepper_motor(speed=0)
        time.sleep(0.2)
except KeyboardInterrupt:
    device._set_stepper_motor(speed=0)
    print("Program interrupted by user")

device.close()




