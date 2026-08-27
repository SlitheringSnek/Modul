# component_visualizer.py
# Handles visualization of detected train components on images, reverted to axis-aligned bounding boxes.

import cv2
import numpy as np # Still needed for array operations, e.g., image copy
import logging

logger = logging.getLogger(__name__)

class ComponentVisualizer:
    """
    A class to handle visualization of component detection results on images.
    This version draws axis-aligned bounding boxes and does not display orientation.
    """

    def __init__(self, config):
        """
        Initialize the Visualizer with configuration settings.

        Args:
            config (dict): Configuration dictionary with visualization parameters.
        """
        self.config = config
        logger.info("ComponentVisualizer initialized with config (axis-aligned boxes).")
        # Define default colors if not in config
        self.bbox_color_map = {
            "yellow": (0, 255, 255), # Yellow in BGR
            "blue": (255, 0, 0),     # Blue in BGR
            "green": (0, 255, 0),    # Green in BGR
            "red": (0, 0, 255)       # Red in BGR
        }
        self.default_color = (128, 128, 128) # Grey for unknown/default

    def _get_color_for_component(self, component_name):
        """
        Determines the drawing color based on the component's color prefix.
        e.g., "yellow-trainBase" -> yellow color.
        """
        parts = component_name.split('-')
        color_prefix = parts[0].lower() if len(parts) > 1 else ""
        return self.bbox_color_map.get(color_prefix, self.default_color)

    def draw_detections(self, image, detections):
        """
        Draws standard bounding boxes, labels, and center points for detected components
        on the input image. Does NOT draw rotated boxes or angles.

        Args:
            image (np.ndarray): The input image (OpenCV format).
            detections (list): A list of dictionaries, where each dictionary
                               represents a detected component.

        Returns:
            np.ndarray: The annotated image.
        """
        if image is None:
            logger.error("Input image for visualization is None.")
            return None

        annotated_image = image.copy()
        font = cv2.FONT_HERSHEY_SIMPLEX

        bbox_thickness = self.config.get("bbox_thickness", 2)
        text_scale = self.config.get("text_scale", 0.6)
        text_thickness = self.config.get("text_thickness", 2)
        circle_radius = self.config.get("circle_radius", 5)
        circle_thickness = self.config.get("circle_thickness", -1) # -1 for filled circle

        if not detections:
            logger.info("No detections to draw.")
            return annotated_image

        for detection in detections:
            name = detection.get('name', 'Unknown')
            confidence = detection.get('confidence', 0.0)
            center_x = detection.get('center_x')
            center_y = detection.get('center_y')
            bbox = detection.get('bbox') # Standard axis-aligned bbox

            if None in [center_x, center_y, bbox]:
                logger.warning(f"Skipping malformed detection for drawing: {detection}")
                continue

            x1, y1, x2, y2 = map(int, bbox) # Ensure bbox coords are integers

            # Get color based on component name
            draw_color = self._get_color_for_component(name)

            # Draw standard axis-aligned bounding box
            cv2.rectangle(annotated_image, (x1, y1), (x2, y2), draw_color, bbox_thickness, cv2.LINE_AA)

            # Draw center point
            cv2.circle(annotated_image, (center_x, center_y), circle_radius, draw_color, circle_thickness)

            # Draw label (name and confidence only)
            label = f"{name} ({confidence:.2f})"
            
            # Position text above the bounding box
            text_size = cv2.getTextSize(label, font, text_scale, text_thickness)[0]
            text_x = x1
            text_y = y1 - 10 if y1 - 10 > text_size[1] else y1 + text_size[1] + 5 # Adjust position to avoid going off-screen top

            cv2.putText(
                annotated_image,
                label,
                (text_x, text_y),
                font,
                text_scale,
                draw_color, # Use the component's color for text
                text_thickness,
                cv2.LINE_AA
            )

        # Optionally add a general count/info on the image
        total_detections = len(detections)
        cv2.putText(
            annotated_image,
            f"Total Components: {total_detections}",
            (10, 30), # Top-left corner
            font,
            0.8, # Larger font for general info
            (255, 255, 255), # White color
            2,
            cv2.LINE_AA
        )

        return annotated_image

