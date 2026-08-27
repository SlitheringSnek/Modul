# utils.py
# Simplified utility functions for the component detection system.

import logging

def setup_logging():
    """
    Configure and set up logging for the application.

    Returns:
        logging.Logger: Configured logger
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(__name__)

