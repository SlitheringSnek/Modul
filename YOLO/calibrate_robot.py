# calibrate_robot.py
# Revised script for camera-to-robot calibration for Dobot Magician.
# Uses lib.interface for Dobot control.
# Captures ONE unobstructed image, identifies 10 numbered corners,
# and guides the user to move the robot (with a pen) to each corresponding physical corner.

import cv2
import numpy as np
import json
import time
import os
import sys
from datetime import datetime
from serial.tools import list_ports
import random # For selecting random calibration points

# --- Corrected path to lib folder ---
# Get the directory of the current script (e.g., 'YOLO')
current_script_dir = os.path.dirname(os.path.abspath(__file__))
# Go up one level from the current script's directory to the parent directory ('modularAssembly')
modular_assembly_dir = os.path.dirname(current_script_dir)
# Insert this 'modularAssembly' directory's path at the beginning of sys.path
sys.path.insert(0, modular_assembly_dir)

try:
    # Now, 'from lib.interface import Interface' should work because 'modular_assembly_dir' is on sys.path
    # and it contains 'lib/' which now has an '__init__.py'
    from lib.interface import Interface
except ImportError as e:
    print(f"Error importing Dobot interface: {e}. Please ensure 'lib' is a Python package "
          f"(contains __init__.py) and its parent directory is in sys.path: {modular_assembly_dir}", file=sys.stderr)
    sys.exit(1) # Exit if essential interface cannot be loaded

# Ensure camera_capture is in the path or same directory (it's in YOLO, so this is fine)
# (current_script_dir is already the YOLO directory)
sys.path.append(current_script_dir) # Redundant if already on path, but harmless
from camera_capture import capture_and_save_single_image

# --- Configuration for Calibration ---
CHECKERBOARD_DIMENSIONS = (3, 3)  # (rows, cols) - INNER corners. For a 4x4 square board, this is 3x3 inner corners.
SQUARE_SIZE_MM = 25.0             # Size of one square on your checkerboard in millimeters (2.5 cm = 25 mm)

# Paths for output and debug images (all relative to IMAGE_CAPTURE_DIR)
IMAGE_CAPTURE_DIR = "calibration_images" # Directory to save temporary calibration images
HOMOGRAPHY_OUTPUT_FILE = "camera_robot_homography.npy" # Path to save the numpy matrix
HOMOGRAPHY_JSON_OUTPUT_FILE = "camera_robot_homography.json" # Path to save JSON representation

# The path where the final output image with drawn corners will be saved for calibration process
FINAL_CALIBRATION_OUTPUT_IMAGE_PATH = os.path.join(IMAGE_CAPTURE_DIR, 'calibration_corners_detected.jpg')

# Debug Image Paths (for viewing intermediate processing steps, saved in IMAGE_CAPTURE_DIR)
DEBUG_ORIGINAL_GRAYSCALE_PATH = os.path.join(IMAGE_CAPTURE_DIR, 'debug_grayscale_original.jpg')
DEBUG_SIMPLE_THRESHOLD_PATH = os.path.join(IMAGE_CAPTURE_DIR, 'debug_grayscale_simple_threshold.jpg')


# --- Simple Thresholding Parameters (DIRECTLY from your working checkerboard_find.py) ---
# These values are crucial for successful detection with simple thresholding.
SIMPLE_THRESH_VALUE = 50        # Threshold value (0-255)
SIMPLE_THRESH_MAX_VALUE = 100   # Max value assigned (usually 255)


NUM_CALIBRATION_POINTS = 5      # Number of points to use for calibration (randomly selected)

# CAMERA_INDEX must be defined BEFORE its use in main_calibration()
CAMERA_INDEX = 0                  # Your camera index (0 is usually default webcam)

# Dobot specific settings (ADJUST THESE CAREFULLY based on your Dobot's real values)
DOBOT_HOME_X = 260.0  # Example home X (adjust to your actual home position)
DOBOT_HOME_Y = 0.0    # Example home Y
DOBOT_HOME_Z = 80.0   # Example home Z (safe height)
DOBOT_HOME_R = 0.0    # Example home R (gripper rotation)

# This Z height is where the Dobot's pen tip *just touches* the checkerboard surface.
# YOU MUST DETERMINE THIS VALUE PRECISELY BY JOGGING THE ROBOT AND READING ITS Z-COORDINATE.
DOBOT_CALIBRATION_Z = -58.0 # Example Z for pen touching the board. VERIFY THIS!

DOBOT_SAFE_Z_MM = 50.0 # A safe Z height for moving between points without collisions

# Global Dobot bot instance for calibration script
bot_instance = None

def connect_to_dobot():
    """
    Connects to the Dobot Magician using lib.interface.
    """
    global bot_instance
    print("Connecting to Dobot Magician...")
    available_ports = list_ports.comports()
    if not available_ports:
        print("No Dobot ports found. Please ensure Dobot is connected.", file=sys.stderr)
        return None

    port = available_ports[0].device
    print(f"Found Dobot on port: {port}")

    try:
        bot = Interface(port) # Your Dobot Interface
        if not bot.connected():
            print("Failed to connect to Dobot.", file=sys.stderr)
            return None

        # You might need to set point-to-point common parameters for velocity/acceleration here
        # For example, to set speed/acceleration for PTP moves:
        # bot.set_point_to_point_common_params(velocity_ratio=50, acceleration_ratio=50, queue=True)
        # Note: If set_point_to_point_common_params does not work ("TODO: Does not work"), you might need to find
        # another way to control speed or just rely on default.

        print("Successfully connected to Dobot.")
        bot_instance = bot
        return bot
    except Exception as e:
        print(f"Failed to connect to Dobot on {port}: {e}", file=sys.stderr)
        return None

def disconnect_from_dobot():
    """
    Disconnects from the Dobot Magician using lib.interface.
    """
    global bot_instance
    if bot_instance:
        print("Disconnecting from Dobot.")
        try:
            bot_instance.disconnect()
        except Exception as e:
            print(f"Error disconnecting Dobot: {e}", file=sys.stderr)
        finally:
            bot_instance = None

def get_dobot_current_pose():
    """
    Reads the Dobot's current X, Y, Z, R coordinates using lib.interface.
    get_pose() returns a list, e.g., [x, y, z, r, j1, j2, j3, j4]
    """
    global bot_instance
    if not bot_instance or not bot_instance.connected():
        print("Dobot not connected. Cannot get pose.", file=sys.stderr)
        return None, None, None, None
    try:
        pose_data = bot_instance.get_pose()
        if pose_data and len(pose_data) >= 4:
            return pose_data[0], pose_data[1], pose_data[2], pose_data[3] # Extract X, Y, Z, R
        else:
            print(f"Warning: get_pose() returned unexpected data: {pose_data}", file=sys.stderr)
            return None, None, None, None
    except Exception as e:
        print(f"Error getting Dobot pose: {e}", file=sys.stderr)
        return None, None, None, None

def move_dobot_to_xyzr(x, y, z, r, wait=True):
    """
    Moves the Dobot to a specified X, Y, Z, R pose using lib.interface.
    Uses set_point_to_point_command with mode 0 (PTP_COMMON or LINE_XYZ).
    """
    global bot_instance
    if not bot_instance or not bot_instance.connected():
        print("Dobot not connected. Cannot move.", file=sys.stderr)
        return False

    print(f"Moving Dobot to X:{x:.2f}, Y:{y:.2f}, Z:{z:.2f}, R:{r:.2f}")
    try:
        # Mode 0 is typically PTP_COMMON or LINE_XYZ in Dobot SDKs for Cartesian movement.
        # We assume queue=True for sequential execution.
        bot_instance.set_point_to_point_command(mode=0, x=x, y=y, z=z, r=r, queue=True)
        # If wait is True, we need to manually wait for the command to finish.
        # Your Interface class does not expose a direct 'wait_for_move_completion' method.
        # For simplicity in calibration, we use a fixed sleep.
        if wait:
            time.sleep(2) # Adjust this sleep time based on Dobot speed and distance
        return True
    except Exception as e:
        print(f"Error moving Dobot to {x},{y},{z},{r}: {e}", file=sys.stderr)
        return False

# This function is the core logic directly from your working checkerboard_find.py
def find_and_draw_chessboard_corners_from_image(img_color, checkerboard_dims,
                                               simple_thresh_val, simple_thresh_max_val,
                                               debug_gray_path, debug_simple_thresh_path,
                                               output_path_final):
    """
    Attempts to find chessboard corners, prioritizing original grayscale,
    then falling back to simple thresholding if grayscale fails.
    Saves debug images and returns found corners.

    Args:
        img_color (np.array): The original color image (NumPy array).
        checkerboard_dims (tuple): A tuple (rows, cols) representing the
                                   inner dimensions of the chessboard pattern.
        simple_thresh_val (int): Threshold value for simple thresholding.
        simple_thresh_max_val (int): Max value for simple thresholding.
        debug_gray_path (str): Path to save the original grayscale debug image.
        debug_simple_thresh_path (str): Path to save the simple thresholded debug image.
        output_path_final (str): Path to save the image with drawn corners if detection succeeds.

    Returns:
        tuple: (ret_status, corners_array) where ret_status is True if corners
               are found, False otherwise, and corners_array is the detected
               corners (or None).
    """
    # Convert the original image to grayscale
    gray_original = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)
    cv2.imwrite(debug_gray_path, gray_original)
    print(f"Debug: Original grayscale image saved to: {debug_gray_path}")

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

    # Use a copy of the original image for drawing, to preserve it for potential drawing later
    img_for_drawing = img_color.copy()

    # --- Attempt 1: Find corners on Original Grayscale Image ---
    print("\n--- Attempting to find corners using: Original Grayscale ---")
    ret, corners = cv2.findChessboardCorners(gray_original, checkerboard_dims, None)

    if ret:
        print("SUCCESS: Corners found using Original Grayscale!")
        corners = cv2.cornerSubPix(gray_original, corners, (11, 11), (-1, -1), criteria)
        cv2.drawChessboardCorners(img_for_drawing, checkerboard_dims, corners, ret) # Draw on the copy
        cv2.imwrite(output_path_final, img_for_drawing)
        print(f"Output image with corners saved to: {output_path_final}")
        return True, corners
    else:
        print("FAILED: No corners found using Original Grayscale. Falling back to Simple Thresholding.")

    # --- Attempt 2: Find corners on Simple Thresholded Image ---
    print("\n--- Attempting to find corners using: Simple Threshold ---")

    # Apply simple thresholding
    ret_val, gray_simple_thresh = cv2.threshold(gray_original, simple_thresh_val,
                                                 simple_thresh_max_val, cv2.THRESH_BINARY)
    cv2.imwrite(debug_simple_thresh_path, gray_simple_thresh)
    print(f"Debug: Simple thresholded image saved to: {debug_simple_thresh_path}")
    print(f"   (Simple Threshold Params: Value={simple_thresh_val}, MaxValue={simple_thresh_max_val})")

    ret, corners = cv2.findChessboardCorners(gray_simple_thresh, checkerboard_dims, None)

    if ret:
        print("SUCCESS: Corners found using Simple Threshold!")
        corners = cv2.cornerSubPix(gray_simple_thresh, corners, (11, 11), (-1, -1), criteria)
        cv2.drawChessboardCorners(img_for_drawing, checkerboard_dims, corners, ret) # Draw on the copy
        cv2.imwrite(output_path_final, img_for_drawing)
        print(f"Output image with corners saved to: {output_path_final}")
        return True, corners
    else:
        print("FAILED: No corners found using Simple Threshold either.")
        print("\nIMPORTANT: No corners were found by any method.")
        print("Consider re-adjusting the SIMPLE_THRESH_VALUE and SIMPLE_THRESH_MAX_VALUE in calibrate_robot.py.")
        print("Also, ensure the physical chessboard is flat, well-lit, and fully visible without glare or obstructions.")
        return False, None


def main_calibration():
    print("\n--- Starting Camera-to-Robot Calibration for Dobot Magician ---")
    print("This process will map camera pixels to Dobot coordinates.")
    print("Ensure your checkerboard is flat on the Dobot's workplane.")
    print("Carefully verify DOBOT_CALIBRATION_Z and DOBOT_SAFE_Z_MM in this script.")

    os.makedirs(IMAGE_CAPTURE_DIR, exist_ok=True)

    # 1. Connect to Dobot
    dobot_device = connect_to_dobot()
    if not dobot_device:
        print("Dobot connection failed. Exiting calibration.", file=sys.stderr)
        return

    input("\n--- Step 1: Capture Unobstructed Checkerboard Image ---\n"
          "Place the checkerboard fully within the camera's view.\n"
          "Ensure the Dobot arm is OUT OF THE CAMERA'S VIEW.\n"
          "Press Enter to capture the image and detect all corners.")

    # Capture ONE image of the full, unobstructed checkerboard
    captured_image_path = capture_and_save_single_image(
        output_dir=IMAGE_CAPTURE_DIR,
        camera_index=CAMERA_INDEX # CAMERA_INDEX is now globally defined at the top
    )

    if not captured_image_path:
        print("Failed to capture image for calibration. Please check camera_capture.py and camera connection. Exiting.", file=sys.stderr)
        disconnect_from_dobot()
        return

    img = cv2.imread(captured_image_path)
    if img is None:
        print(f"Failed to load calibration image: {captured_image_path}. Exiting.", file=sys.stderr)
        disconnect_from_dobot()
        return

    # NEW: Call the adapted working function directly
    ret, corners = find_and_draw_chessboard_corners_from_image(
        img,
        CHECKERBOARD_DIMENSIONS,
        SIMPLE_THRESH_VALUE,
        SIMPLE_THRESH_MAX_VALUE,
        DEBUG_ORIGINAL_GRAYSCALE_PATH,
        DEBUG_SIMPLE_THRESHOLD_PATH,
        FINAL_CALIBRATION_OUTPUT_IMAGE_PATH
    )

    if not ret: # If corners were not found by either method
        print("ERROR: Could not find checkerboard corners in the captured image using any method. Please ensure:\n"
              "- The checkerboard is fully visible (no cropped corners) and well-lit.\n"
              "- CHECKERBOARD_DIMENSIONS (rows, cols of INNER corners) is correct for your board.\n"
              "- The Dobot arm is not obstructing the view during this capture.\n"
              "- Review 'debug_grayscale_original.jpg' and 'debug_grayscale_simple_threshold.jpg' in your 'calibration_images' folder for clarity.\n"
              "- Adjust SIMPLE_THRESH_VALUE and SIMPLE_THRESH_MAX_VALUE in calibrate_robot.py if necessary.\n"
              "Exiting calibration.", file=sys.stderr)
        disconnect_from_dobot()
        return

    # If corners were found, 'corners' already contains the refined subpixel coordinates

    # Flatten corners array to (N, 2)
    corners_2d = corners.reshape(-1, 2)

    # Sort corners for consistent mapping (e.g., row-major order: top-left to bottom-right)
    # Sorting by Y-coordinate primarily, then by X-coordinate to ensure consistent order
    corners_2d = corners_2d[np.lexsort((corners_2d[:, 0], corners_2d[:, 1]))]


    print(f"Found {len(corners_2d)} checkerboard corners in total.")

    if len(corners_2d) < NUM_CALIBRATION_POINTS:
        print(f"ERROR: Only {len(corners_2d)} corners found, but need {NUM_CALIBRATION_POINTS} for calibration.", file=sys.stderr)
        print("Please use a checkerboard with enough visible corners or reduce NUM_CALIBRATION_POINTS.", file=sys.stderr)
        disconnect_from_dobot()
        return

    # Randomly select NUM_CALIBRATION_POINTS unique corners for calibration
    selected_indices = random.sample(range(len(corners_2d)), NUM_CALIBRATION_POINTS)
    selected_indices.sort() # Sort selected indices for a predictable manual jogging order

    # Prepare image for drawing selected points (this is separate from the one saved by the detection function)
    img_for_drawing_calib_points = img.copy()

    print(f"Selected {NUM_CALIBRATION_POINTS} points for calibration. These will be marked on 'calibration_points_marked.jpg'.")
    print("Please refer to this image when jogging the Dobot arm to each numbered point.")

    # Draw and save selected corners with numbers for user verification
    for idx, corner_index in enumerate(selected_indices):
        pixel_point = (int(corners_2d[corner_index][0]), int(corners_2d[corner_index][1]))

        # Draw red circle
        cv2.circle(img_for_drawing_calib_points, pixel_point, 10, (0, 0, 255), -1) # Red circle, filled

        # Draw number next to the point
        cv2.putText(img_for_drawing_calib_points, str(idx + 1),
                    (pixel_point[0] + 15, pixel_point[1] - 10), # Offset to place text
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)

    marked_image_path = os.path.join(IMAGE_CAPTURE_DIR, f"calibration_points_marked_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    cv2.imwrite(marked_image_path, img_for_drawing_calib_points)
    print(f"Marked calibration points saved for reference: {marked_image_path}")


    camera_points_px = []  # To store (pixel_u, pixel_v) for homography
    robot_points_mm = []   # To store (robot_x_mm, robot_y_mm) for homography

    input("\n--- Step 2: Record Robot Coordinates for Each Marked Corner ---\n"
          "Now, you will manually jog the Dobot's end-effector (with your pen) to EACH MARKED corner.\n"
          f"Ensure the pen tip is at DOBOT_CALIBRATION_Z HEIGHT ({DOBOT_CALIBRATION_Z:.2f}mm) when recording position.\n"
          "Refer to the saved 'calibration_points_marked.jpg' for the numbered points.\n"
          "Press Enter when Dobot is in position to record its X,Y...")

    # Iterate through the SELECTED camera corners and get the corresponding robot point
    for i, corner_index in enumerate(selected_indices):
        u, v = corners_2d[corner_index] # Get the pixel coordinates of the current selected corner

        print(f"\n--- Calibrating Point {i+1}/{NUM_CALIBRATION_POINTS} ---")
        print(f"Target Camera Pixel: ({u:.2f}, {v:.2f})")

        input(f"Move Dobot's pen tip to the physical location of MARKED POINT {i+1} ({u:.0f}, {v:.0f}) on the checkerboard.\n"
              f"Ensure its Z-height is at DOBOT_CALIBRATION_Z ({DOBOT_CALIBRATION_Z:.2f}mm).\n"
              f"Press Enter when Dobot is in position to record its X,Y...")

        current_x, current_y, current_z, current_r = get_dobot_current_pose()
        if current_x is None:
            print("Failed to get Dobot's current pose. Exiting calibration.", file=sys.stderr)
            break

        # Confirm the Dobot is at the correct Z-height for calibration
        if abs(current_z - DOBOT_CALIBRATION_Z) > 1.0: # Allow 1mm tolerance
            print(f"WARNING: Dobot Z-height ({current_z:.2f}mm) is not at expected calibration Z ({DOBOT_CALIBRATION_Z:.2f}mm) for point {i+1}.", file=sys.stderr)
            print("Proceeding with current X,Y but ensure Z is correct for final operation accuracy.", file=sys.stderr)

        robot_points_mm.append((current_x, current_y))
        camera_points_px.append((u, v)) # Add the pixel point that corresponds to this robot point
        print(f"Recorded Dobot (X,Y) for point {i+1}: ({current_x:.2f}mm, {current_y:.2f}mm)")

        # Move Dobot to a safe position after recording each point
        if i < NUM_CALIBRATION_POINTS - 1: # Only move to safe position if there are more points to calibrate
            if not move_dobot_to_xyzr(DOBOT_HOME_X, DOBOT_HOME_Y, DOBOT_SAFE_Z_MM, DOBOT_HOME_R, wait=True):
                print("Failed to move Dobot to safe position. Exiting.", file=sys.stderr)
                break

    # Final move to home
    print("\nCalibration points collected. Moving Dobot to safe home position...")
    move_dobot_to_xyzr(DOBOT_HOME_X, DOBOT_HOME_Y, DOBOT_HOME_Z, DOBOT_HOME_R, wait=True) # Return to DOBOT_HOME_Z
    disconnect_from_dobot() # Close Dobot connection

    if len(camera_points_px) < 4: # Still need at least 4 for homography, just in case
        print(f"ERROR: Not enough unique points collected for homography. Need at least 4, collected {len(camera_points_px)}. Exiting.", file=sys.stderr)
        return

    # Convert lists to NumPy arrays for homography calculation
    camera_points_np = np.array(camera_points_px, dtype=np.float32)
    robot_points_np = np.array(robot_points_mm, dtype=np.float32)

    # Calculate the Homography Matrix
    print("\nCalculating Homography Matrix...")
    H, _ = cv2.findHomography(camera_points_np, robot_points_np, cv2.RANSAC, 5.0)

    if H is None:
        print("ERROR: Failed to calculate homography. This usually means your point correspondences are incorrect or insufficient.", file=sys.stderr)
        return

    print("\nCalculated Homography Matrix (H):\n", H)

    # Save the homography matrix to file
    np.save(HOMOGRAPHY_OUTPUT_FILE, H)
    with open(HOMOGRAPHY_JSON_OUTPUT_FILE, 'w') as f:
        json.dump(H.tolist(), f, indent=4)
    print(f"Homography matrix saved to {HOMOGRAPHY_OUTPUT_FILE} and {HOMOGRAPHY_JSON_OUTPUT_FILE}")

    print("\n--- Calibration Complete ---")
    print("The robot is now calibrated to the camera's view.")
    print(f"To run detection and robot actions, set 'calibration_mode': False in main.py.")

if __name__ == "__main__":
    main_calibration()
