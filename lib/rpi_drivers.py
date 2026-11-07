import importlib
from lib.log_setup import logger

# Read at import time, before the hardware drivers are initialized. Changes to
# this setting require a service restart.
def _hat_disabled():
    from pathlib import Path
    from xml.etree import ElementTree
    try:
        path = Path(__file__).resolve().parent.parent / "config" / "settings.xml"
        return ElementTree.parse(path).getroot().findtext("disable_hat") == "1"
    except (OSError, ElementTree.ParseError):
        return False


HAT_DISABLED = _hat_disabled()
gpio_backend = "null"
RPiException = None
if HAT_DISABLED:
    from lib.null_drivers import GPIOnull
    GPIO = GPIOnull()
    logger.info("disable_hat=1: LCD HAT GPIO disabled until restart.")
else:
    try:
        GPIO = importlib.import_module("RPi.GPIO")
        gpio_backend = "RPi.GPIO"
    except Exception as e:
        try:
            GPIO = importlib.import_module("rpi_lgpio.RPi.GPIO")
            gpio_backend = "rpi_lgpio"
        except Exception:
            logger.warning(f"RPi GPIO not available ({e}), using null driver.")
            RPiException = e
            from lib.null_drivers import GPIOnull
            GPIO = GPIOnull()

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
