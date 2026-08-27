# component_detector.py
# Handles detection of train components using YOLO, run locally in-process via the
# Roboflow `inference` SDK (no Docker / inference server required), and conditionally
# calculates their orientation using OpenCV post-processing.
# NOW INCLUDES LOGIC TO SWAP 'trainBase' and 'trainWheels' names.

import cv2
import logging
import numpy as np
from inference import get_model

logger = logging.getLogger(__name__)

class ComponentDetector:
    """
    Class for detecting train components in images using a YOLO API
    and conditionally calculating their orientation.
    """

    def __init__(self, config):
        """
        Initialize the component detector with configuration.

        Args:
            config (dict): Configuration dictionary containing the Roboflow model ID,
                           API key, confidence threshold, and orientation detection settings.
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.model_id = config["model_id"]
        self.api_key = config["api_key"]
        self.confidence_threshold = config["confidence_threshold"]
        self.enable_orientation_detection = config.get("enable_orientation_detection", True)

        # Components for which orientation detection should always be skipped
        self.no_orientation_components = ['chimney', 'cabin']

        # Loads the trained Roboflow model and runs it locally in-process (no Docker /
        # inference server needed). On first use this downloads and caches the model
        # weights, which requires internet access and the API key; subsequent runs load
        # the cached weights and can run fully offline.
        self.logger.info(f"Loading Roboflow model '{self.model_id}' for local inference...")
        self.model = get_model(model_id=self.model_id, api_key=self.api_key)
        self.logger.info("Model loaded.")

        if self.enable_orientation_detection:
            self.logger.info("Global orientation detection is ENABLED.")
            self.logger.info(f"Orientation will be SKIPPED for: {', '.join(self.no_orientation_components)}")
        else:
            self.logger.info("Global orientation detection is DISABLED.")


    def _calculate_orientation(self, image, bbox, component_name):
        """
        Calculates the orientation angle of an object within a given bounding box.
        Uses contour finding and minAreaRect.

        Args:
            image (np.ndarray): The full input image (BGR).
            bbox (tuple): (x1, y1, x2, y2) of the YOLO detected bounding box.
            component_name (str): The name of the detected component (e.g., "yellow-trainBase").

        Returns:
            tuple: ((center_x, center_y), (width, height), angle) representing the
                   rotated bounding box, and the normalized angle (0-90 degrees).
                   Returns None, None if orientation cannot be calculated or if
                   the component type is configured to skip orientation.
        """
        # Check if orientation should be skipped for this specific component
        # We use the potentially SWAPPED name here for consistency with the rest of the pipeline
        base_component_name = component_name.split('-')[-1].lower() 
        if any(no_orient_part in base_component_name for no_orient_part in self.no_orientation_components):
            self.logger.info(f"Skipping orientation calculation for '{component_name}' as configured.")
            return None, None

        x1, y1, x2, y2 = map(int, bbox)
        
        # Ensure coordinates are valid and within image bounds
        h, w = image.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        # Check if bbox is valid (has positive dimensions)
        if x2 <= x1 or y2 <= y1:
            self.logger.warning(f"Invalid bounding box dimensions for orientation calculation ({component_name}): {bbox}. Skipping.")
            return None, None

        # Crop the image to the bounding box
        cropped_roi = image[y1:y2, x1:x2]

        if cropped_roi.size == 0:
            self.logger.warning(f"Cropped ROI is empty for bbox ({component_name}): {bbox}. Cannot calculate orientation.")
            return None, None

        try:
            # Convert to grayscale
            gray_roi = cv2.cvtColor(cropped_roi, cv2.COLOR_BGR2GRAY)

            # Apply Gaussian blur to reduce noise
            blurred_roi = cv2.GaussianBlur(gray_roi, (5, 5), 0)

            # Use Canny edge detection
            # You might need to tune these thresholds based on your object's appearance
            edges = cv2.Canny(blurred_roi, 50, 150) 

            # Find contours
            # Using cv2.RETR_EXTERNAL to retrieve only extreme outer contours
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if not contours:
                self.logger.warning(f"No contours found in the cropped ROI for '{component_name}'. Cannot determine orientation.")
                return None, None

            # Find the largest contour (assumed to be the object of interest)
            largest_contour = max(contours, key=cv2.contourArea)

            if cv2.contourArea(largest_contour) < 100: # Filter out very small contours
                self.logger.warning(f"Largest contour for '{component_name}' is too small. Skipping orientation calculation.")
                return None, None

            # Calculate the minimum area rotated rectangle
            rect = cv2.minAreaRect(largest_contour) # ((center_x, center_y), (width, height), angle)

            # The center coordinates from minAreaRect are relative to the cropped ROI.
            # Convert them back to original image coordinates.
            rotated_center_x_global = rect[0][0] + x1
            rotated_center_y_global = rect[0][1] + y1
            rotated_center_global = (rotated_center_x_global, rotated_center_y_global)

            # Normalize angle: cv2.minAreaRect returns angle in [-90, 0)
            # This logic transforms it to [0, 90] where 0 is horizontal and 90 is vertical
            # The angle represents the angle between the horizontal axis and the first side of the rectangle.
            # If width < height, the angle is closer to -90. If width > height, closer to 0.
            angle = rect[2]
            width_rect, height_rect = rect[1] # Renamed to avoid conflict with YOLO width/height

            if width_rect < height_rect:
                angle = angle + 90 # Adjust to make 0-90 where 0 is horizontal, 90 is vertical

            # Return the rotated bounding box (global coordinates) and the normalized angle
            return (rotated_center_global, (width_rect, height_rect), angle), angle

        except Exception as e:
            self.logger.error(f"Error calculating orientation for '{component_name}' (bbox {bbox}): {e}")
            return None, None

    def detect_components(self, image):
        """
        Detect train components in an image using the locally loaded YOLO model.
        If enabled, also conditionally calculates component orientation.
        Includes logic to swap 'trainBase' and 'trainWheels' names.

        Args:
            image (np.ndarray): Input image (OpenCV format).

        Returns:
            list: List of dictionaries, each representing a detected component
                  with keys: 'name', 'confidence', 'center_x', 'center_y',
                  'bbox' (tuple: x1, y1, x2, y2), and optionally 'rotated_bbox'
                  and 'angle_degrees'.
                  Returns an empty list if no detections or on error.
        """
        if image is None:
            self.logger.error("Input image for detection is None.")
            return []

        try:
            # model.infer() accepts a BGR numpy array directly (same format cv2.imread
            # returns), runs entirely in-process, and applies the confidence threshold
            # itself. results is a list (one entry per input image); we pass a single image.
            results = self.model.infer(image, confidence=self.confidence_threshold)[0]
            predictions = results.predictions
            self.logger.debug(f"Received {len(predictions)} predictions from local model.")

            detected_components = []
            for pred in predictions:
                x_center = pred.x
                y_center = pred.y
                width = pred.width
                height = pred.height
                confidence = pred.confidence
                class_name_raw = pred.class_name # Get the raw class name from YOLO

                # --- Name Swapping Logic ---
                class_name_processed = class_name_raw
                if "trainBase" in class_name_raw:
                    # Assuming format like "color-trainBase"
                    class_name_processed = class_name_raw.replace("trainBase", "trainWheels")
                    self.logger.debug(f"Swapped '{class_name_raw}' to '{class_name_processed}'")
                elif "trainWheels" in class_name_raw:
                    # Assuming format like "color-trainWheels"
                    class_name_processed = class_name_raw.replace("trainWheels", "trainBase")
                    self.logger.debug(f"Swapped '{class_name_raw}' to '{class_name_processed}'")
                # --- End Name Swapping Logic ---


                x1 = int(x_center - width / 2)
                y1 = int(y_center - height / 2)
                x2 = int(x_center + width / 2)
                y2 = int(y_center + height / 2)

                center_x_round = int(x_center)
                center_y_round = int(y_center)

                component_data = {
                    'name': class_name_processed, # Use the processed name
                    'confidence': confidence,
                    'center_x': center_x_round,
                    'center_y': center_y_round,
                    'bbox': (x1, y1, x2, y2)
                }

                if self.enable_orientation_detection:
                    # Pass the processed component_name to _calculate_orientation for conditional skipping
                    rotated_bbox, angle = self._calculate_orientation(image, (x1, y1, x2, y2), class_name_processed)
                    if rotated_bbox is not None:
                        component_data['rotated_bbox'] = rotated_bbox
                        component_data['angle_degrees'] = angle
                
                detected_components.append(component_data)

            self.logger.info(f"Detected {len(detected_components)} components after filtering (including conditional orientation and name swap).")
            return detected_components

        except Exception as e:
            self.logger.error(f"An unexpected error occurred during detection: {e}")
            self.logger.exception(e)
            return []
