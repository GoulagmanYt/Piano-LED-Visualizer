import importlib
from lib.log_setup import logger

# GPIO
gpio_backend = "null"
RPiException = None
try:
    # 1. Standard RPi.GPIO (or rpi-lgpio if it replaces RPi.GPIO)
    GPIO = importlib.import_module("RPi.GPIO")
    gpio_backend = "RPi.GPIO"
except Exception as e:
    try:
        # 2. rpi_lgpio (Raspberry Pi 5 / Bookworm)
        GPIO = importlib.import_module("rpi_lgpio.RPi.GPIO")
        gpio_backend = "rpi_lgpio"
    except Exception:
        logger.warning(f"RPi GPIO not available ({e}), using null driver.")
        RPiException = e
        from lib.null_drivers import GPIOnull
        GPIO = GPIOnull()
        gpio_backend = "null"

# rpi_ws281x
try:
    _ws_mod = importlib.import_module("rpi_ws281x")
    PixelStrip = getattr(_ws_mod, "PixelStrip", None)
    ws = getattr(_ws_mod, "ws", None)
    Color = getattr(_ws_mod, "Color", None)
except ModuleNotFoundError as e:
    logger.warning("Module rpi_ws281x not found, using null driver.")
    from lib.null_drivers import Color
    PixelStrip = None
    ws = None

# spidev
try:
    spidev = importlib.import_module("spidev")
except ModuleNotFoundError as e:
    logger.warning("Module spidev not found.")
    spidev = None
