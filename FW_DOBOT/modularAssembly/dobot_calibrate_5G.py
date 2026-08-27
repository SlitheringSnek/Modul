import sys
import os
import time
from serial.tools import list_ports
from lib.interface import Interface
sys.path.insert(0, os.path.abspath('.'))

available_ports = list_ports.comports()
port = available_ports[0].device
#print(f'available ports: {[x.device for x in available_ports]}')

bot = Interface(port)

#print('Bot status:', 'connected' if bot.connected() else 'not connected')

params = bot.get_homing_paramaters()
#print('Params:', params)

#print('Homing')
bot.set_homing_command(0) # tukaj gre na homing position

time.sleep(20)

print("Calibration finished")
