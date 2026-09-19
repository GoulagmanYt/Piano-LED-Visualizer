"""
Animation utilities - Common functions for LED animations
"""
import time
from lib.functions import fastColorWipe
from lib.log_setup import logger


def stop_and_wait(menu):
    """
    Stop animations and wait for cleanup.
    
    Args:
        menu: MenuLCD instance
    """
    menu.is_animation_running = False
    menu.is_idle_animation_running = False
    time.sleep(0.2)


def stop_and_prepare(menu, ledstrip, ledsettings):
    """
    Stop animations, wait, and prepare LED strip.
    
    Args:
        menu: MenuLCD instance
        ledstrip: LedStrip instance
        ledsettings: LedSettings instance
    """
    stop_and_wait(menu)
    strip = ledstrip.strip
    fastColorWipe(strip, True, ledsettings)
    return strip


def get_animation_speed(speed_ms=None, default_speed="medium"):
    """
    Get animation speed with fallback to default.
    
    Args:
        speed_ms: Custom speed in milliseconds
        default_speed: Default speed setting
        
    Returns:
        int: Speed in milliseconds
    """
    if speed_ms is not None:
        return speed_ms
    
    from lib.animation_speed import get_global_speed_ms
    return get_global_speed_ms(default_speed)


def calculate_brightness_percent(ledsettings):
    """
    Calculate brightness as percentage.
    
    Args:
        ledsettings: LedSettings instance
        
    Returns:
        float: Brightness as decimal (0-1)
    """
    brightness = ledsettings.led_animation_brightness_percent
    return brightness / 100.0
