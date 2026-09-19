"""
Color utilities - Optimized color calculations and caching
"""
import colorsys
from functools import lru_cache
from lib.rpi_drivers import Color
from lib.functions import clamp


class ColorCache:
    """Cache for frequently used color calculations"""
    
    def __init__(self, max_size=1000):
        self.max_size = max_size
        self._cache = {}
        self._access_order = []
    
    def get(self, key):
        """Get cached color by key"""
        if key in self._cache:
            # Move to end (LRU)
            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]
        return None
    
    def put(self, key, value):
        """Put color in cache"""
        if key in self._cache:
            self._access_order.remove(key)
        elif len(self._cache) >= self.max_size:
            # Remove least recently used
            oldest = self._access_order.pop(0)
            del self._cache[oldest]
        
        self._cache[key] = value
        self._access_order.append(key)


# Global color cache instance
_color_cache = ColorCache()


@lru_cache(maxsize=256)
def cached_rgb_to_hsv(r, g, b):
    """Cached RGB to HSV conversion"""
    return colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)


@lru_cache(maxsize=256)
def cached_hsv_to_rgb(h, s, v):
    """Cached HSV to RGB conversion"""
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))


def create_color_optimized(r, g, b):
    """Optimized color creation with caching"""
    # Clamp values first
    r = clamp(r, 0, 255)
    g = clamp(g, 0, 255)
    b = clamp(b, 0, 255)
    
    # Check cache first
    cache_key = (r, g, b)
    cached_color = _color_cache.get(cache_key)
    if cached_color is not None:
        return cached_color
    
    # Create and cache new color
    color = Color(int(r), int(g), int(b))
    _color_cache.put(cache_key, color)
    return color


def blend_colors_optimized(color1, color2, ratio):
    """Optimized color blending"""
    ratio = clamp(ratio, 0.0, 1.0)
    inv_ratio = 1.0 - ratio
    
    r = int(color1[0] * inv_ratio + color2[0] * ratio)
    g = int(color1[1] * inv_ratio + color2[1] * ratio)
    b = int(color1[2] * inv_ratio + color2[2] * ratio)
    
    return create_color_optimized(r, g, b)


def adjust_brightness_optimized(color, brightness_factor):
    """Optimized brightness adjustment"""
    brightness_factor = clamp(brightness_factor, 0.0, 1.0)
    
    r = int(color[0] * brightness_factor)
    g = int(color[1] * brightness_factor)
    b = int(color[2] * brightness_factor)
    
    return create_color_optimized(r, g, b)


def rainbow_color_optimized(pos, brightness=1.0):
    """Optimized rainbow color generation"""
    pos = int(pos) % 256
    brightness = clamp(brightness, 0.0, 1.0)
    
    if pos < 85:
        r = pos * 3
        g = 255 - pos * 3
        b = 0
    elif pos < 170:
        pos -= 85
        r = 255 - pos * 3
        g = 0
        b = pos * 3
    else:
        pos -= 170
        r = 0
        g = pos * 3
        b = 255 - pos * 3
    
    return adjust_brightness_optimized((r, g, b), brightness)


def clear_color_cache():
    """Clear the color cache"""
    global _color_cache
    _color_cache = ColorCache()
    cached_rgb_to_hsv.cache_clear()
    cached_hsv_to_rgb.cache_clear()
