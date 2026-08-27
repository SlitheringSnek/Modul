import cv2
import numpy as np
import os

# --- Configuration Variables ---

# Define the dimensions of your chessboard pattern (rows, columns).
# For your 4x4 grid of squares, the inner corners are 3x3.
CHECKERBOARD_DIMENSIONS = (3, 3) # (inner_rows, inner_cols)

# Path to your input image.
INPUT_IMAGE_PATH = '/home/pi/Desktop/FW_DOBOT/modularAssembly/YOLO/calibration_images/captured_image_20250619_144604.jpg'

# Path where the final output image with drawn corners will be saved.
FINAL_OUTPUT_IMAGE_PATH = 'chessboard_corners_detected.jpg'

# --- Debug Image Paths (for viewing intermediate processing steps) ---
DEBUG_ORIGINAL_GRAYSCALE_PATH = 'debug_grayscale_original.jpg'
DEBUG_SIMPLE_THRESHOLD_PATH = 'debug_grayscale_simple_threshold.jpg'


# --- Simple Thresholding Parameters (tuned based on your successful attempt) ---
# Adjust these values as needed if your lighting conditions change.
SIMPLE_THRESH_VALUE = 50        # Threshold value (0-255) - pixels below this are set to 0 (black)
SIMPLE_THRESH_MAX_VALUE = 100   # Max value assigned (usually 255) - pixels above SIMPLE_THRESH_VALUE are set to this


# --- Main Script ---

def find_and_draw_chessboard_corners_optimized(input_path, output_path,
                                               debug_gray_path, debug_simple_thresh_path,
                                               checkerboard_dims,
                                               simple_thresh_val, simple_thresh_max_val):
    """
    Loads an image, attempts to find chessboard corners first on grayscale,
    then falls back to simple thresholding if grayscale fails.
    Saves debug images for both methods and the final output.

    Args:
        input_path (str): The path to the input image.
        output_path (str): The path to save the final image with corners drawn.
        debug_gray_path (str): Path to save the original grayscale debug image.
        debug_simple_thresh_path (str): Path to save the simple thresholded debug image.
        checkerboard_dims (tuple): A tuple (rows, cols) representing the
                                   inner dimensions of the chessboard pattern.
        simple_thresh_val (int): Threshold value for simple thresholding.
        simple_thresh_max_val (int): Max value for simple thresholding.
    """
    print(f"Loading image from: {input_path}")
    img_color = cv2.imread(input_path)

    if img_color is None:
        print(f"Error: Could not load image from {input_path}. Please check the path and filename.")
        print("Ensure the image file exists and is accessible.")
        return

    print(f"Image loaded successfully. Dimensions: {img_color.shape}")

    # Convert the original image to grayscale
    gray_original = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)
    cv2.imwrite(debug_gray_path, gray_original)
    print(f"Debug: Original grayscale image saved to: {debug_gray_path}")

    # --- Attempt 1: Find corners on Original Grayscale Image ---
    print("\n--- Attempting to find corners using: Original Grayscale ---")
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)

    # Use a copy of the original image for drawing, to preserve it
    img_with_corners = img_color.copy()

    ret, corners = cv2.findChessboardCorners(gray_original, checkerboard_dims, None)

    if ret:
        print("SUCCESS: Corners found using Original Grayscale!")
        corners = cv2.cornerSubPix(gray_original, corners, (11, 11), (-1, -1), criteria)
        cv2.drawChessboardCorners(img_with_corners, checkerboard_dims, corners, ret)
        cv2.imwrite(output_path, img_with_corners)
        print(f"Final image with corners saved to: {output_path}")
        return # Corners found, exit function
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

    # Use a fresh copy of the original image for drawing if this attempt succeeds
    img_with_corners_simple_thresh = img_color.copy()

    ret, corners = cv2.findChessboardCorners(gray_simple_thresh, checkerboard_dims, None)

    if ret:
        print("SUCCESS: Corners found using Simple Threshold!")
        corners = cv2.cornerSubPix(gray_simple_thresh, corners, (11, 11), (-1, -1), criteria)
        cv2.drawChessboardCorners(img_with_corners_simple_thresh, checkerboard_dims, corners, ret)
        cv2.imwrite(output_path, img_with_corners_simple_thresh)
        print(f"Final image with corners saved to: {output_path}")
    else:
        print("FAILED: No corners found using Simple Threshold either.")
        print("\nIMPORTANT: No corners were found by any method.")
        print("Consider re-adjusting the SIMPLE_THRESH_VALUE and SIMPLE_THRESH_MAX_VALUE.")
        print("Also, ensure the physical chessboard is flat, well-lit, and fully visible without glare or obstructions.")


if __name__ == "__main__":
    find_and_draw_chessboard_corners_optimized(
        INPUT_IMAGE_PATH,
        FINAL_OUTPUT_IMAGE_PATH,
        DEBUG_ORIGINAL_GRAYSCALE_PATH,
        DEBUG_SIMPLE_THRESHOLD_PATH,
        CHECKERBOARD_DIMENSIONS,
        SIMPLE_THRESH_VALUE,
        SIMPLE_THRESH_MAX_VALUE
    )
