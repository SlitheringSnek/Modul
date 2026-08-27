# main.py
# Orchestrates image capture, local YOLO-based component detection, visualization,
# and UPDATES the movement_data.json.txt file with detected component coordinates.
# It DOES NOT perform robot movements in normal operation; these are handled by assembly_NR1.py.

import os
os.environ['MVCAM_COMMON_RUNENV'] = '/opt/MVS'

import json
import logging
import sys
import time
import numpy as np
from datetime import datetime
from collections import defaultdict
import subprocess # To run external robot calibration script
import cv2 # Ensure cv2 is imported if used elsewhere in main.py, e.g., for image loading

####
# Open a log file for writing
log_file = open("/home/pi/Desktop/YOLO/output.log", "w")

# Redirect stdout and stderr
sys.stdout = log_file
sys.stderr = log_file
#original_stdout = sys.stdout
#original_stderr = sys.stderr
####

# Custom module imports
from utils import setup_logging
from camera_capture import capture_and_save_single_image
from component_detector import ComponentDetector
from component_visualizer import ComponentVisualizer

# Import camera-robot calibration script (will be run conditionally)
import calibrate_robot
# NEW: Import the robot manager for data updating (and calibration Dobot control)
import robot_manager

# Configure logging for the main application
logger = setup_logging()

# --- DEFAULT CONFIGURATION ---
DEFAULT_CONFIG = {
    "calibration_mode": False, # Set to False for normal operation (data update mode)

    # Camera Capture Settings
    "camera_index": 0,
    "captured_images_dir": "/home/pi/Desktop/YOLO/captured_images", #ABSOLITE PATH

    # YOLO Model Settings (loaded and run locally in-process via the Roboflow `inference`
    # SDK - no Docker / inference server required. First run downloads and caches the
    # model weights using api_key; later runs can use the cached weights offline.)
    "model_id": "train-parts-yolo/1",
    #"model_id": "poskus-oznaka-zgornje-ploskve/5",
    "api_key": os.environ.get("ROBOFLOW_API_KEY", ""), # set ROBOFLOW_API_KEY in the environment, don't hardcode it here
    "confidence_threshold": 0.5,

    # Orientation Detection Setting (used in component_detector)
    "enable_orientation_detection": True,

    # Visualization Settings
    "output_results_dir": "/home/pi/Desktop/YOLO/detection_results", #ABSOLITE PATH
    "bbox_thickness": 2,
    "text_scale": 0.6,
    "text_thickness": 1,
    "circle_radius": 5,
    "circle_thickness": -1,

    # Robot Calibration & Movement Settings
    "HOMOGRAPHY_MATRIX_PATH": "/home/pi/Desktop/YOLO/camera_robot_homography.npy", # Path to saved homography matrix ABSOLUTE PATH
    "DOBOT_FIRMWARE_CALIBRATION_SCRIPT_PATH": "/home/pi/Desktop/FW_DOBOT/modularAssembly/dobot_calibrate_5G.py",

    # Dobot Home Position (should align with calibrate_robot.py)
    "DOBOT_HOME_X": 260.0,
    "DOBOT_HOME_Y": 0.0,
    "DOBOT_HOME_Z": 80.0,
    "DOBOT_HOME_R": 0.0,
    "DOBOT_SAFE_Z_MM": 50.0, # A safe Z height for robot movement

    # Movement Data Path
    "MOVEMENT_DATA_PATH": "/home/pi/Desktop/FW_DOBOT/modularAssembly/movement_data", # Path to your JSON file with movement sequences
}

def generate_component_counts(detections):
    """
    Generates a structured count of components by part type and color,
    wrapped in a 'components_count' key for ThingsBoard.
    """
    component_counts_raw = defaultdict(lambda: defaultdict(int))
    for detection in detections:
        full_name = detection.get('name')
        if not full_name or '-' not in full_name:
            logger.warning(f"Skipping malformed component name for counting: {full_name}")
            continue
        try:
            color, part_name = full_name.split('-', 1)
            component_counts_raw[part_name][color] += 1
        except ValueError:
            logger.warning(f"Component name '{full_name}' does not fit 'color-partName' format for counting.")
            continue
    
    # Convert defaultdicts to regular dicts for cleaner JSON output
    final_counts = {
        part: dict(colors) for part, colors in component_counts_raw.items()
    }

    # Wrap the final counts in the desired "components_count" key
    return {"components_count": final_counts}


# def generate_component_counts(detections):
#     """
#     Generates a structured count of components by part type and color.
#     """
#     component_counts = defaultdict(lambda: defaultdict(int))
#     for detection in detections:
#         full_name = detection.get('name')
#         if not full_name or '-' not in full_name:
#             logger.warning(f"Skipping malformed component name for counting: {full_name}")
#             continue
#         try:
#             color, part_name = full_name.split('-', 1)
#             component_counts[part_name][color] += 1
#         except ValueError:
#             logger.warning(f"Component name '{full_name}' does not fit 'color-partName' format for counting.")
#             continue
#     return component_counts # Return defaultdicts for easier use if iterating later.

def run_detection_pipeline():
    """
    Runs the image capture, detection, and visualization pipeline.
    """
    os.makedirs(DEFAULT_CONFIG["captured_images_dir"], exist_ok=True)
    os.makedirs(DEFAULT_CONFIG["output_results_dir"], exist_ok=True)
    
    print("FOLDER", DEFAULT_CONFIG["captured_images_dir"])
    
    captured_image_path = capture_and_save_single_image(
        output_dir=DEFAULT_CONFIG["captured_images_dir"],
        #output_dir=DEFAULT_CONFIG["/home/pi/Desktop/YOLO/captured_images"]
        camera_index=DEFAULT_CONFIG["camera_index"]
    )
    
    if not captured_image_path:
        logger.error("Failed to capture image. Exiting detection pipeline.")
        return False, None # Indicate failure and no components

    logger.info(f"Image captured successfully: {captured_image_path}")

    try:
        image = cv2.imread(captured_image_path)
        if image is None:
            raise ValueError(f"Failed to load image from {captured_image_path}")
        logger.info(f"Image loaded: {captured_image_path}")
    except Exception as e:
        logger.error(f"Error loading captured image: {e}")
        return False, None

    detector = ComponentDetector(DEFAULT_CONFIG)
    detected_components = detector.detect_components(image)

    if not detected_components:
        logger.warning("No components detected in the image.")
    else:
        logger.info(f"Detected {len(detected_components)} components.")

    visualizer = ComponentVisualizer(DEFAULT_CONFIG)
    annotated_image = visualizer.draw_detections(image, detected_components)

    if annotated_image is None:
        logger.error("Failed to generate annotated image. Exiting detection pipeline.")
        return False, None

    # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # annotated_filename = f"detected_components_{timestamp}.jpg"
    # detection_data_filename = f"detection_data_{timestamp}.json"
    # component_counts_filename = f"component_counts_{timestamp}.json"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    annotated_filename = f"detected_components_{timestamp}.jpg"
    detection_data_filename = f"detection_data_{timestamp}.json"
    component_counts_filename = f"component_counts.json"

    annotated_image_path = os.path.join(DEFAULT_CONFIG["output_results_dir"], annotated_filename)
    detection_data_path = os.path.join(DEFAULT_CONFIG["output_results_dir"], detection_data_filename)
    component_counts_path = os.path.join(DEFAULT_CONFIG["output_results_dir"], component_counts_filename)

    try:
        cv2.imwrite(annotated_image_path, annotated_image)
        logger.info(f"Annotated image saved to: {annotated_image_path}")
    except Exception as e:
        logger.error(f"Error saving annotated image: {e}")

    try:
        with open(detection_data_path, 'w') as f:
            json.dump(detected_components, f, indent=4)
        logger.info(f"Detailed detection data saved to: {detection_data_path}")
    except Exception as e:
        logger.error(f"Error saving detailed detection data: {e}")

    component_counts = generate_component_counts(detected_components)
    try:
        # Convert defaultdicts to regular dicts for cleaner JSON output
        final_counts_for_json = {
            part: dict(colors) for part, colors in component_counts.items()
        }
        with open(component_counts_path, 'w') as f:
            json.dump(final_counts_for_json, f, indent=4)
        logger.info(f"Component counts saved to: {component_counts_path}")
    except Exception as e:
        logger.error(f"Error saving component counts: {e}")

    logger.info("Detection pipeline finished successfully.")
    return True, detected_components


def run_dobot_only_calibration(script_path):
    """
    Executes the external Dobot-only calibration script.
    """
    logger.info(f"Starting Dobot-only calibration script: {script_path}")
    if not os.path.exists(script_path):
        logger.error(f"Dobot-only calibration script not found at: {script_path}")
        return False

    try:
        result = subprocess.run([sys.executable, script_path], capture_output=True, text=True, check=True)
        logger.info("Dobot-only calibration script completed successfully.")
        if result.stdout:
            logger.info(f"Script stdout:\n{result.stdout}")
        if result.stderr:
            logger.warning(f"Script stderr:\n{result.stderr}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Dobot-only calibration script failed with error code {e.returncode}.")
        logger.error(f"Script stdout:\n{e.stdout}")
        logger.error(f"Script stderr:\n{e.stderr}")
        return False
    except FileNotFoundError:
        logger.error(f"Python interpreter or script not found at path: {script_path}", file=sys.stderr)
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred while running Dobot-only calibration script: {e}", file=sys.stderr)
        return False


def main():
    """
    Main function to run the pipeline: camera capture, YOLO detection (run locally
    in-process), visualization, and either robot calibration OR updating movement
    data for external assembly script.
    """
    logger.info("Starting main pipeline...")

    # --- Calibration Mode ---
    if DEFAULT_CONFIG["calibration_mode"]:
        logger.info("Running in CALIBRATION MODE.")

        # 1. Initialize robot manager for calibration (connects Dobot)
        dobot_conn_successful = robot_manager.init_robot_manager_for_calibration(DEFAULT_CONFIG, logger)
        if not dobot_conn_successful:
            logger.error("Failed to connect to Dobot for calibration. Aborting.")
            return

        # 2. Run the Dobot-only firmware calibration script FIRST
        if not run_dobot_only_calibration(DEFAULT_CONFIG["DOBOT_FIRMWARE_CALIBRATION_SCRIPT_PATH"]):
            logger.error("Dobot firmware calibration failed. Aborting main pipeline.")
            robot_manager.disconnect_robot_manager() # Disconnect Dobot on failure
            return # Abort if firmware calibration fails

        # 3. Then run the camera-robot calibration script
        calibrate_robot.main_calibration()
        logger.info("Calibration mode finished. Exiting main pipeline.")
        robot_manager.disconnect_robot_manager() # Disconnect Dobot after calibration
        return # Exit after calibration

    # --- Normal Operation (calibration_mode = False) ---
    logger.info("Running in NORMAL OPERATION MODE (Updating Movement Data).")

    # Run the detection pipeline
    success, detected_components = run_detection_pipeline()

    if success:
        logger.info("Proceeding to update movement data based on detected components.")

        # Load the homography matrix
        homography_matrix = None
        try:
            homography_matrix = np.load(DEFAULT_CONFIG["HOMOGRAPHY_MATRIX_PATH"])
            logger.info(f"Loaded homography matrix from: {DEFAULT_CONFIG['HOMOGRAPHY_MATRIX_PATH']}")
        except FileNotFoundError:
            logger.error(f"Homography matrix not found at {DEFAULT_CONFIG['HOMOGRAPHY_MATRIX_PATH']}. Cannot update movement data.")
            return # Exit if homography is missing
        except Exception as e:
            logger.error(f"Error loading homography matrix: {e}. Cannot update movement data.")
            return
        try:
            # Load the base movement data
            base_movement_data = robot_manager.load_movement_data(DEFAULT_CONFIG["MOVEMENT_DATA_PATH"], logger)
            if base_movement_data is None:
                logger.error("Failed to load base movement data. Cannot proceed with updates.")
                return

            # Update movement data with detected coordinatesl
            if detected_components:
                print("pizdarija", detected_components)
                #print("pizdarija", str(detected_components), file=original_stdout, flush=True)
                updated_movement_data = robot_manager.update_movement_data_with_detected_coords(
                    detected_components, homography_matrix, base_movement_data, DEFAULT_CONFIG, logger
                )
                if updated_movement_data:
                    # Save the updated movement data back to the file
                    robot_manager.save_movement_data(updated_movement_data, DEFAULT_CONFIG["MOVEMENT_DATA_PATH"], logger)
                    logger.info("Movement data file has been updated with detected pick-up coordinates.")
                else:
                    logger.error("Failed to generate updated movement data from detections.")
            else:
                logger.info("No components detected. Movement data file will not be updated with new pick-up coordinates.")

            logger.info("Normal operation (movement data update) finished.")

        except Exception as e:
            print(e)
            raise e

    else:
        logger.error("Detection pipeline failed, skipping movement data update.")


if __name__ == "__main__":
    main()
