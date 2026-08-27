import os
import time
import sys
#import paho.mqtt.client as mqtt
import json
import pydobot
from serial.tools import list_ports
from pydobotplus import Dobot, CustomPosition
import ast

#poskusna vrstica za ssh prek VSCode

start_time = time.time()

# This file is currently supporting assembly of next train parts: engine, cabin, chimney
def parse_operation_from_file(file_path):
	"""
	This function reads the JSON string provided by NodeRed. It then acquires the part and color data and saves it in a dictionary.
	The dictionary is then used to call the right data for assembly.
	"""
	# Read the JSON string from the .txt file
	with open(file_path, 'r') as file:
		json_string = file.read()

	# Parse the JSON string
	data = json.loads(json_string)

	# Extract the relevant data
	part_name = data["currentOperation"]["data"]["part"]
	part_color = data["currentOperation"]["data"]["color"]
	details = data["currentOperation"]

	# Store the data in a dictionary
	parts_dict = {}
	key = (part_name, part_color)
	parts_dict[key] = details

	return parts_dict

def read_data_file(file_path):
	# Read the content of the text file
	with open(file_path, 'r') as file:
		content = file.read()

	# Use ast.literal_eval to safely evaluate the string content as a Python literal
	data_dict = ast.literal_eval(content)

	return data_dict

def get_data_array(data_dict, part_name, color):
	# Get the list of arrays for the specified part
	part_data = data_dict.get(part_name, [])

	# Map colors to indices (assuming the order is red, blue, green, yellow)
	color_map = {
		"red": 0,
		"green": 1,
		"blue": 2,
		"yellow": 3
	}

	# Get the index for the specified color
	color_index = color_map.get(color)

	if color_index is not None and color_index < len(part_data):
		return part_data[color_index]
	else:
		return None

def robot_operation(device, coords):
	'''
	Starts the robot with data for each operation.
	'''
	device.speed(150, 150)
	for move in coords:
		try:
			x, y, z, r = map(float, move[:4])
		except ValueError as e:
			print(f"Error converting values to float: {e}")
			continue
		device.move_to(x, y, z, r, wait=True)
		device.suck(bool(move[5]))

# ZACETEK PROGRAMA
# Initialize Dobot
available_ports = list_ports.comports()
port = available_ports[0].device
device = Dobot(port=port)

# Read JSON string from file
file_path = "/home/pi/Desktop/FW_DOBOT/modularAssembly/order_data"  # POZOR!
part_data = parse_operation_from_file(file_path)

# Read data array for current subpart
file_path = '/home/pi/Desktop/FW_DOBOT/modularAssembly/movement_data'  # POZOR!
all_points = read_data_file(file_path)

# Extract part name and color from the parsed data
part_name = list(part_data.keys())[0][0]
color = list(part_data.keys())[0][1]

# Get the coordinates for the part and color
part_coords = get_data_array(all_points, part_name, color)
print(part_coords)

# Robot operation
robot_operation(device, part_coords)
t0 = time.time()
# Close the connection to the Dobot

t1 = time.time()

#print(f"Time of code snippet: {t1-t0}")

elapsed_time = float("{:.2f}".format(time.time() - start_time))
#print(f"Elapsed time of entire code: {elapsed_time}")
#print(f"End of assembly of {color} {part_name}")
print("END")

device.close()
