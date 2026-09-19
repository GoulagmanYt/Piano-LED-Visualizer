"""
LED Animation Optimizer - Performance improvements for LED animations
"""
import time
import threading
from collections import deque
from functools import lru_cache
from typing import Dict, List, Tuple
from lib.log_setup import logger


class AnimationFrameCache:
    """Cache for animation frames to reduce redundant calculations"""
    
    def __init__(self, max_frames=1000):
        self.max_frames = max_frames
        self._cache = {}
        self._access_times = {}
        self._lock = threading.Lock()
    
    def get_frame(self, key: str) -> List:
        """Get cached frame by key"""
        with self._lock:
            if key in self._cache:
                self._access_times[key] = time.time()
                return self._cache[key].copy()
            return None
    
    def store_frame(self, key: str, frame_data: List):
        """Store frame data in cache"""
        with self._lock:
            # Remove oldest frame if cache is full
            if len(self._cache) >= self.max_frames:
                oldest_key = min(self._access_times.keys(), 
                               key=lambda k: self._access_times[k])
                del self._cache[oldest_key]
                del self._access_times[oldest_key]
            
            self._cache[key] = frame_data.copy()
            self._access_times[key] = time.time()
    
    def clear(self):
        """Clear all cached frames"""
        with self._lock:
            self._cache.clear()
            self._access_times.clear()


class AnimationPerformanceTracker:
    """Track animation performance metrics"""
    
    def __init__(self, window_size=50):
        self.window_size = window_size
        self.frame_times = deque(maxlen=window_size)
        self.fps_history = deque(maxlen=window_size)
        self.last_frame_time = 0
    
    def record_frame(self, frame_time: float):
        """Record frame timing"""
        self.frame_times.append(frame_time)
        
        # Calculate FPS
        if self.last_frame_time > 0:
            fps = 1.0 / (frame_time - self.last_frame_time)
            self.fps_history.append(fps)
        
        self.last_frame_time = frame_time
    
    def get_average_fps(self) -> float:
        """Get average FPS over the window"""
        if not self.fps_history:
            return 0.0
        return sum(self.fps_history) / len(self.fps_history)
    
    def get_average_frame_time(self) -> float:
        """Get average frame time"""
        if not self.frame_times:
            return 0.0
        return sum(self.frame_times) / len(self.frame_times)


class OptimizedAnimationEngine:
    """Optimized animation engine with frame skipping and adaptive quality"""
    
    def __init__(self, target_fps=30):
        self.target_fps = target_fps
        self.target_frame_time = 1.0 / target_fps
        self.frame_cache = AnimationFrameCache()
        self.performance_tracker = AnimationPerformanceTracker()
        self.adaptive_quality = True
        self.current_quality = 1.0
        self.frame_skip_counter = 0
        
    def should_skip_frame(self) -> bool:
        """Determine if current frame should be skipped for performance"""
        if not self.adaptive_quality:
            return False
        
        avg_fps = self.performance_tracker.get_average_fps()
        if avg_fps > 0 and avg_fps < self.target_fps * 0.8:
            # Performance is below target, consider frame skipping
            self.frame_skip_counter += 1
            return self.frame_skip_counter % 2 == 0  # Skip every other frame
        
        self.frame_skip_counter = 0
        return False
    
    def adjust_quality(self, performance_ratio: float):
        """Adjust animation quality based on performance"""
        if not self.adaptive_quality:
            return
        
        if performance_ratio < 0.7:  # Running at less than 70% target performance
            self.current_quality = max(0.5, self.current_quality * 0.95)
        elif performance_ratio > 1.2:  # Running well above target
            self.current_quality = min(1.0, self.current_quality * 1.02)
    
    def get_cached_frame(self, animation_name: str, frame_num: int, 
                        params: Tuple = ()) -> List:
        """Get cached animation frame or compute if needed"""
        cache_key = f"{animation_name}_{frame_num}_{hash(params)}"
        
        # Try cache first
        cached_frame = self.frame_cache.get_frame(cache_key)
        if cached_frame is not None:
            return cached_frame
        
        return None
    
    def cache_frame(self, animation_name: str, frame_num: int, 
                   frame_data: List, params: Tuple = ()):
        """Cache computed animation frame"""
        cache_key = f"{animation_name}_{frame_num}_{hash(params)}"
        self.frame_cache.store_frame(cache_key, frame_data)
    
    def start_frame_timing(self):
        """Start timing a new frame"""
        return time.perf_counter()
    
    def end_frame_timing(self, start_time: float):
        """End frame timing and record metrics"""
        frame_time = time.perf_counter()
        self.performance_tracker.record_frame(frame_time)
        
        # Adjust quality based on performance
        avg_frame_time = self.performance_tracker.get_average_frame_time()
        if avg_frame_time > 0:
            performance_ratio = self.target_frame_time / avg_frame_time
            self.adjust_quality(performance_ratio)


# Global animation engine instance
_animation_engine = OptimizedAnimationEngine()


def get_animation_engine():
    """Get the global animation engine"""
    return _animation_engine


@lru_cache(maxsize=128)
def cached_interpolate_color(color1: Tuple, color2: Tuple, ratio: float) -> Tuple:
    """Cached color interpolation for animations"""
    ratio = max(0.0, min(1.0, ratio))
    inv_ratio = 1.0 - ratio
    
    return (
        int(color1[0] * inv_ratio + color2[0] * ratio),
        int(color1[1] * inv_ratio + color2[1] * ratio),
        int(color1[2] * inv_ratio + color2[2] * ratio)
    )


def optimize_animation_loop(animation_func, *args, **kwargs):
    """
    Wrapper for animation functions with performance optimization.
    
    Args:
        animation_func: The animation function to optimize
        *args, **kwargs: Arguments to pass to the animation function
    
    Returns:
        Optimized animation function
    """
    def optimized_wrapper(*wrapper_args, **wrapper_kwargs):
        engine = get_animation_engine()
        
        # Check if frame should be skipped
        if engine.should_skip_frame():
            return
        
        # Start timing
        start_time = engine.start_frame_timing()
        
        try:
            # Call original animation function
            result = animation_func(*wrapper_args, **wrapper_kwargs)
            return result
        finally:
            # End timing and record metrics
            engine.end_frame_timing(start_time)
    
    return optimized_wrapper


def precompute_animation_frames(animation_func, frame_count: int, 
                             animation_name: str, *args, **kwargs):
    """
    Precompute animation frames for smoother playback.
    
    Args:
        animation_func: Animation function
        frame_count: Number of frames to precompute
        animation_name: Name for caching
        *args, **kwargs: Animation arguments
    """
    engine = get_animation_engine()
    
    for frame_num in range(frame_count):
        # Check if frame is already cached
        cached_frame = engine.get_cached_frame(animation_name, frame_num, args)
        if cached_frame is not None:
            continue
        
        # Compute and cache frame
        frame_data = animation_func(frame_num, *args, **kwargs)
        engine.cache_frame(animation_name, frame_num, frame_data, args)


def clear_animation_cache():
    """Clear all animation caches"""
    global _animation_engine
    _animation_engine.frame_cache.clear()
    cached_interpolate_color.cache_clear()
    logger.info("Animation cache cleared")


def get_animation_stats():
    """Get animation performance statistics"""
    engine = get_animation_engine()
    return {
        'average_fps': engine.performance_tracker.get_average_fps(),
        'average_frame_time_ms': engine.performance_tracker.get_average_frame_time() * 1000,
        'current_quality': engine.current_quality,
        'cache_size': len(engine.frame_cache._cache)
    }
