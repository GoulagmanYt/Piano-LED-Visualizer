import logging
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener
import queue
import sys
import os
from pathlib import Path

# Create a custom logger
logger = logging.getLogger("my_app")

# Set the level of this logger.
logger.setLevel(logging.DEBUG)

# Create handlers
console_handler = logging.StreamHandler()
log_path = Path(os.environ.get('PLV_LOG_PATH', str(Path(__file__).resolve().parents[1] / 'visualizer.log')))
file_handler = RotatingFileHandler(log_path, maxBytes=500000, backupCount=10, delay=True)

# Set the level for handlers
console_handler.setLevel(logging.DEBUG)
file_handler.setLevel(logging.DEBUG)

# Create formatters and add it to handlers
formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s',
                              datefmt='%Y-%m-%d %H:%M:%S')
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# Asynchronous non-blocking logging queue: eliminates SD card flush stalls on render loop
_log_queue = queue.SimpleQueue()
_queue_handler = QueueHandler(_log_queue)
_listener = QueueListener(_log_queue, console_handler, file_handler, respect_handler_level=True)
_listener.start()

# Add queue handler to the logger
logger.addHandler(_queue_handler)

# Custom exception handler to log unhandled exceptions
def log_unhandled_exception(exc_type, exc_value, exc_traceback):
    logger.error("Unhandled Exception: ", exc_info=(exc_type, exc_value, exc_traceback))

# Set the custom exception handler
sys.excepthook = log_unhandled_exception

def apply_log_setting(disable_logs):
    if str(disable_logs) == '1' or str(disable_logs).lower() == 'true':
        logger.setLevel(logging.CRITICAL + 1)
        console_handler.setLevel(logging.CRITICAL + 1)
        file_handler.setLevel(logging.CRITICAL + 1)
        logging.disable(logging.CRITICAL)
    else:
        logger.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.DEBUG)
        file_handler.setLevel(logging.DEBUG)
        logging.disable(logging.NOTSET)
