"""Linear power estimate for a snapshot of intended, pre-gamma RGB pixels."""

import math
import operator


POWER_DEFAULTS = {
    "led_ma_per_channel": 20.0,
    "led_idle_ma": 1.0,
    "led_supply_voltage": 5.0,
}


def parse_power_setting(name, value):
    """Validate one calibration value without changing persisted settings."""
    if name not in POWER_DEFAULTS:
        raise ValueError("Unknown LED power setting")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("LED power calibration must be a finite number") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError("LED power calibration must be finite and nonnegative")
    if name == "led_supply_voltage" and number == 0:
        raise ValueError("LED supply voltage must be positive")
    return number


def estimate_led_power(pixels, brightness, settings=None):
    """Return finite JSON values; invalid data raises ValueError.

    The caller supplies a copied pixel sequence and the driver's integer
    brightness. This model excludes gamma, the Pi and wiring losses.
    """
    try:
        brightness = operator.index(brightness)
    except TypeError as exc:
        raise ValueError("LED brightness must be an integer from 0 to 255") from exc
    if not 0 <= brightness <= 255:
        raise ValueError("LED brightness must be an integer from 0 to 255")

    calibration = {}
    for name, default in POWER_DEFAULTS.items():
        value = settings.get(name) if settings is not None else None
        if value is None or value == "":
            value = default
        calibration[name] = parse_power_setting(name, value)

    channel_sum = 0
    for pixel in pixels:
        try:
            pixel = operator.index(pixel)
        except TypeError as exc:
            raise ValueError("LED pixels must be packed RGB integers") from exc
        if not 0 <= pixel <= 0xFFFFFF:
            raise ValueError("LED pixels must be packed RGB integers")
        channel_sum += ((pixel >> 16) & 255) + ((pixel >> 8) & 255) + (pixel & 255)

    try:
        idle_ma = len(pixels) * calibration["led_idle_ma"]
        lit_ma = (channel_sum / 255.0) * calibration["led_ma_per_channel"] * (brightness / 255.0)
        current_a = (idle_ma + lit_ma) / 1000.0
        maximum_a = (idle_ma + len(pixels) * 3 * calibration["led_ma_per_channel"]) / 1000.0
        power_w = current_a * calibration["led_supply_voltage"]
    except OverflowError as exc:
        raise ValueError("LED power estimate exceeds the numeric range") from exc
    if not all(math.isfinite(value) for value in (current_a, maximum_a, power_w)):
        raise ValueError("LED power estimate exceeds the numeric range")

    return {
        "available": True,
        "led_current_a": round(current_a, 2),
        "led_power_w": round(power_w, 1),
        "led_current_max_a": round(maximum_a, 2),
        **calibration,
    }
