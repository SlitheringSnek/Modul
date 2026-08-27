# robot_manager.py
# This module handles Dobot connection (primarily for calibration),
# coordinate transformation, and updating movement data based on detected components.
# It no longer performs pick-and-place execution in normal operation mode.

import json
import logging
import time
import numpy as np
import sys
import os

# --- Corrected path to lib folder ---
current_script_dir = os.path.dirname(os.path.abspath(__file__))
modular_assembly_dir = os.path.dirname(current_script_dir)
sys.path.insert(0, modular_assembly_dir)

try:
    from lib.interface import Interface
    from serial.tools import list_ports
    import cv2 # Import OpenCV for homography transformation
except ImportError as e:
    logging.getLogger(__name__).error(f"Required libraries not found: {e}. Robot functions might be limited.")
    Interface = None
    list_ports = None
    cv2 = None

# Global Dobot bot instance for this module (used mainly for calibration)
_dobot_bot_instance = None
# Logger instance
_logger = None

def init_robot_manager_for_calibration(config, logger):
    """
    Initializes the robot manager for calibration mode by connecting to the Dobot.
    Movement data is NOT loaded here as it's not needed for calibration.
    """
    global _dobot_bot_instance, _logger
    _logger = logger # Store the logger instance

    _logger.info("Initializing Robot Manager for Calibration...")

    # Connect to Dobot
    _dobot_bot_instance = connect_to_dobot(logger)
    if _dobot_bot_instance:
        _logger.info("Dobot connected for calibration. Performing initial homing and safe move.")
        try:
            _dobot_bot_instance.set_homing_command(0) # Your specific homing command
            time.sleep(20) # Wait for homing to complete
            _logger.info("Homing finished.")
        except Exception as e:
            _logger.error(f"Error during Dobot homing: {e}. Please ensure set_homing_command is correct in interface.py.", file=sys.stderr)

        move_dobot_to_xyzr(config["DOBOT_HOME_X"], config["DOBOT_HOME_Y"],
                           config["DOBOT_HOME_Z"], config["DOBOT_HOME_R"], wait=True, logger=_logger)
    else:
        _logger.warning("Dobot not connected for calibration. Calibration functions might not work.")

    _logger.info("Robot Manager initialized for Calibration.")
    return _dobot_bot_instance is not None # Return True if Dobot connected, False otherwise

def disconnect_robot_manager():
    """
    Cleans up Dobot connection.
    """
    global _dobot_bot_instance
    if _dobot_bot_instance:
        _logger.info("Setting Dobot instance to None for cleanup.")
        _dobot_bot_instance = None


def connect_to_dobot(logger):
    """
    Connects to the Dobot Magician using lib.interface.
    """
    if Interface is None or list_ports is None:
        logger.error("Dobot Interface or list_ports not available. Cannot connect to Dobot.")
        return None

    logger.info("Attempting to connect to Dobot Magician...")
    available_ports = list_ports.comports()
    if not available_ports:
        logger.error("No Dobot ports found. Please ensure Dobot is connected.")
        return None

    port = available_ports[0].device
    logger.info(f"Found Dobot on port: {port}")

    try:
        bot = Interface(port)
        if not bot.connected():
            logger.error("Failed to connect to Dobot via Interface. Check connection.")
            return None
        logger.info("Successfully connected to Dobot.")
        return bot
    except Exception as e:
        logger.error(f"Failed to connect to Dobot on {port}: {e}")
        return None

def move_dobot_to_xyzr(x, y, z, r, wait=True, logger=None):
    """
    Moves the Dobot to a specific X, Y, Z, R pose using lib.interface.
    This function is primarily for calibration use within this module.
    """
    if not _dobot_bot_instance or not _dobot_bot_instance.connected():
        logger.error("Dobot is not connected for movement. This function is for calibration/testing only.")
        return False

    logger.info(f"Moving Dobot to X:{x:.2f}, Y:{y:.2f}, Z:{z:.2f}, R:{r:.2f}")
    try:
        _dobot_bot_instance.set_point_to_point_command(mode=0, x=x, y=y, z=z, r=r, queue=True)
        if wait:
            time.sleep(2)
        return True
    except Exception as e:
        logger.error(f"Error moving Dobot to {x},{y},{z},{r}: {e}")
        return False

def dobot_suck(enable, logger=None):
    """
    Helper function to control Dobot suction cup using lib.interface.
    This function is primarily for calibration use within this module.
    """
    if not _dobot_bot_instance or not _dobot_bot_instance.connected():
        logger.error("Dobot is not connected for suction. This function is for calibration/testing only.")
        return False

    logger.info(f"Setting suction to {enable}")
    try:
        _dobot_bot_instance.set_end_effector_suction_cup(enable_control=1, enable_suction=enable, queue=True)
        time.sleep(0.5)
        return True
    except Exception as e:
        logger.error(f"Error controlling Dobot suction: {e}")
        return False

def transform_pixel_to_robot_coords(pixel_x, pixel_y, homography_matrix, logger=None):
    """
    Transforms a single pixel coordinate to robot arm coordinates using the homography matrix.
    """
    if cv2 is None:
        logger.error("OpenCV (cv2) not available for coordinate transformation.")
        return None, None
    if homography_matrix is None:
        logger.error("Homography matrix not loaded. Cannot transform coordinates.")
        return None, None

    src_point = np.array([[[pixel_x, pixel_y]]], dtype=np.float32)
    transformed_point = cv2.perspectiveTransform(src_point, homography_matrix)
    robot_x = transformed_point[0][0][0]
    robot_y = transformed_point[0][0][1]
    return robot_x, robot_y

def load_movement_data(file_path, logger):
    """Loads movement data from a JSON file."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        logger.info(f"Movement data loaded successfully from {file_path}")
        return data
    except FileNotFoundError:
        logger.error(f"Movement data file not found at: {file_path}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON from {file_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading movement data: {e}")
        return None

def convert_numpy_types_to_python_types(obj):
    """
    Recursively converts NumPy types (like float32, int64) to native Python types
    (float, int) to make them JSON serializable.
    """
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_numpy_types_to_python_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types_to_python_types(elem) for elem in obj]
    else:
        return obj

def save_movement_data(data, file_path, logger):
    """Saves movement data to a JSON file, converting NumPy types for serialization."""
    try:
        # Convert NumPy types to standard Python types before saving
        serializable_data = convert_numpy_types_to_python_types(data)
        with open(file_path, 'w') as f:
            json.dump(serializable_data, f, indent=4)
        logger.info(f"Movement data saved successfully to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving movement data to {file_path}: {e}")
        return False

def get_movement_sequence_template(part_type, color_name, all_movements, logger):
    """
    Retrieves a deep copy of the movement sequence template for a specific part type and color.
    Assumes all_movements structure: {"part_type": [red_moves, green_moves, blue_moves, yellow_moves]}
    and the color_map provided by the user.
    """
    color_map = {
        "red": 0,
        "green": 1,
        "blue": 2,
        "yellow": 3
    }

    if part_type not in all_movements:
        logger.error(f"Part type '{part_type}' not found in movement data.")
        return None
    if color_name not in color_map:
        logger.error(f"Color '{color_name}' not found in color map.")
        return None

    color_index = color_map[color_name]
    if color_index >= len(all_movements[part_type]):
        logger.error(f"No movement sequence for color '{color_name}' ({color_index}) in part type '{part_type}'.")
        return None

    # Return a deep copy to prevent modifying the original loaded data
    return [list(step) for step in all_movements[part_type][color_index]]

def update_movement_data_with_detected_coords(detected_components, homography_matrix, base_movement_data, config, logger):
    """
    Takes detected components and a base movement data dictionary,
    updates the pick-up X, Y coordinates for each detected component,
    including the approach and retract moves around the pick-up point.
    Returns the updated movement data dictionary.
    No robot movements are performed here.
    """
    if base_movement_data is None:
        logger.error("Base movement data is None. Cannot update coordinates.")
        return None

    # Create a deep copy of the base movement data to modify
    updated_movement_data = json.loads(json.dumps(base_movement_data))

    logger.info("Updating movement data with detected component coordinates...")

    for component in detected_components:
        full_name = component['name']
        if '-' not in full_name:
            logger.warning(f"Skipping malformed component name: {full_name}")
            continue

        try:
            part_color, part_type = full_name.split('-', 1)
        except ValueError:
            logger.warning(f"Component name '{full_name}' does not fit 'color-partName' format. Skipping.")
            continue

        pixel_center_x = component['center_x']
        pixel_center_y = component['center_y']

        robot_x, robot_y = transform_pixel_to_robot_coords(
            pixel_center_x, pixel_center_y, homography_matrix, logger
        )

        if robot_x is None or robot_y is None:
            logger.error(f"Failed to transform coordinates for {full_name}. Skipping update for this component.")
            continue

        logger.info(f"Detected '{full_name}' at pixel ({pixel_center_x}, {pixel_center_y}) -> Robot X:{robot_x:.2f}mm, Y:{robot_y:.2f}mm")

        # Get the specific sequence for this part type and color from the *updated_movement_data* copy
        color_map = {
            "red": 0, "green": 1, "blue": 2, "yellow": 3
        }
        color_index = color_map.get(part_color)

        if part_type not in updated_movement_data or color_index is None or color_index >= len(updated_movement_data[part_type]):
            logger.error(f"Could not find existing movement sequence for {full_name} in the base movement data. Skipping update.")
            continue

        # Get a direct reference to the list of moves for this component within the updated data
        target_moves_list = updated_movement_data[part_type][color_index]

        # Find the pick-up move (where suck_enable == 1)
        pick_move_index = -1
        for i, move_step in enumerate(target_moves_list):
            # Assuming suck_enable is at index 4
            if len(move_step) > 4 and move_step[4] == 1:
                pick_move_index = i
                break

        if pick_move_index != -1:
            # Update X and Y of the pick-up move itself
            target_moves_list[pick_move_index][0] = robot_x
            target_moves_list[pick_move_index][1] = robot_y
            logger.info(f"Updated pick-up move at index {pick_move_index} for {full_name} to X:{robot_x:.2f}, Y:{robot_y:.2f}.")

            # Update X and Y of the move immediately before (approach) if it exists
            if pick_move_index > 0:
                # Check if the Z coordinate of the previous move is higher than the pick move
                # This helps confirm it's an approach move
                if target_moves_list[pick_move_index - 1][2] > target_moves_list[pick_move_index][2]:
                    target_moves_list[pick_move_index - 1][0] = robot_x
                    target_moves_list[pick_move_index - 1][1] = robot_y
                    logger.info(f"Updated approach move at index {pick_move_index - 1} for {full_name} to X:{robot_x:.2f}, Y:{robot_y:.2f}.")
                else:
                    logger.warning(f"Preceding move at index {pick_move_index - 1} for {full_name} does not appear to be an approach move (Z not higher). X,Y not updated for it.")
            else:
                logger.warning(f"No preceding move found for pick-up at index {pick_move_index}. Cannot update approach X,Y.")

            # Update X and Y of the move immediately after (retract) if it exists
            if pick_move_index < len(target_moves_list) - 1:
                # Check if the Z coordinate of the next move is higher than the pick move
                # This helps confirm it's a retract move
                if target_moves_list[pick_move_index + 1][2] > target_moves_list[pick_move_index][2]:
                    target_moves_list[pick_move_index + 1][0] = robot_x
                    target_moves_list[pick_move_index + 1][1] = robot_y
                    logger.info(f"Updated retract move at index {pick_move_index + 1} for {full_name} to X:{robot_x:.2f}, Y:{robot_y:.2f}.")
                else:
                    logger.warning(f"Subsequent move at index {pick_move_index + 1} for {full_name} does not appear to be a retract move (Z not higher). X,Y not updated for it.")
            else:
                logger.warning(f"No subsequent move found for pick-up at index {pick_move_index}. Cannot update retract X,Y.")

        else:
            logger.warning(f"Could not identify pick-up move (suck_enable=1) in the sequence for {full_name}. X,Y not updated for any step.")

    logger.info("Finished updating movement data with detected component coordinates.")
    return updated_movement_data

# This block allows you to test robot_manager.py independently if needed by runing python robot_manager.py
# It allows you to test the functions within robot_manager.py (like load_movement_data, update_movement_data_with_detected_coords) in isolation, 
# without needing to run the entire main.py pipeline or have a physical Dobot connected
if __name__ == "__main__":
    # Example usage for testing purposes only
    print("This is a test run of robot_manager.py. It primarily tests data loading and updating.")
    # Setup dummy config for testing
    test_config = {
        "DOBOT_HOME_X": 260.0, "DOBOT_HOME_Y": 0.0, "DOBOT_HOME_Z": 80.0, "DOBOT_HOME_R": 0.0,
        "MOVEMENT_DATA_PATH": "/home/pi/Desktop/FW_DOBOT/modularAssembly/movement_data", # Adjust path if testing from different location
    }
    # Setup a simple logger for testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    test_logger = logging.getLogger("RobotManagerTest")

    # Test data loading and updating (without Dobot connection unless needed for calibration part)
    # Create a dummy movement data structure for testing the JSON serialization fix
    dummy_base_data = {
        "trainBase": [
            [
                [260.0, 0.0, 80.0, 0.0, 0, 0],
                [0.0, 240.0, 30.0, 90.0, 0, 0],
                [90.0, 175.0, -40.0, 90.0, 0, 0], # Approach
                [90.0, 175.0, -58.0, 90.0, 1, 1], # Pick-up
                [90.0, 175.0, -40.0, 90.0, 0, 1], # Retract
                [0.0, 240.0, 30.0, 90.0, 0, 1],
                [255.0, 194.0, 40.0, 90.0, 0, 1],
                [255.0, 194.0, -3.0, 90.0, 1, 0],
                [255.0, 194.0, 40.0, 90.0, 0, 0],
                [260.0, 0.0, 80.0, 0.0, 0, 0]
            ]
        ]
    }

    # Simulate loading from file by using the dummy data directly
    # In real scenario, load_movement_data would read from actual file
    base_data = dummy_base_data # For testing the serialization directly

    if base_data:
        test_logger.info("Base movement data loaded.")
        # Create a dummy homography matrix (replace with a real one for actual testing)
        dummy_homography = np.array([
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1]
        ], dtype=np.float32)

        # Create dummy detected components
        dummy_components = [
            {"name": "green-trainBase", "center_x": 100, "center_y": 150},
            {"name": "blue-trainBase", "center_x": 200, "center_y": 250}
        ]

        updated_data = update_movement_data_with_detected_coords(
            dummy_components, dummy_homography, base_data, test_config, test_logger
        )

        if updated_data:
            test_logger.info("Updated movement data (in memory):")
            # print(json.dumps(updated_data, indent=4)) # Uncomment to see the updated data

            # Test saving the updated data to a temporary file
            temp_output_path = "updated_movement_data_test.json.txt"
            save_movement_data(updated_data, temp_output_path, test_logger)
            test_logger.info(f"Updated data saved to {temp_output_path} for verification.")
        else:
            test_logger.error("Failed to get updated movement data.")
    else:
        test_logger.error("Failed to load base movement data for testing.")

