"""
Colormap memory optimization - Efficient colormap generation and caching
"""
import numpy as np
import gc
from functools import lru_cache
from threading import Lock
from typing import Dict, List, Tuple, Optional
from lib.log_setup import logger


class ColormapMemoryManager:
    """Manages colormap memory usage with intelligent caching"""
    
    def __init__(self, max_memory_mb=50, max_colormaps=20):
        self.max_memory_mb = max_memory_mb
        self.max_colormaps = max_colormaps
        self.colormap_cache = {}
        self.access_times = {}
        self.memory_usage = 0
        self._lock = Lock()
        
        # Track memory statistics
        self.cache_hits = 0
        self.cache_misses = 0
        self.evictions = 0
    
    def _estimate_colormap_size(self, colormap_data: np.ndarray) -> int:
        """Estimate memory usage of a colormap in bytes"""
        return colormap_data.nbytes
    
    def _get_current_memory_mb(self) -> float:
        """Get current memory usage in MB"""
        return self.memory_usage / (1024 * 1024)
    
    def _evict_least_recently_used(self) -> Optional[str]:
        """Evict the least recently used colormap"""
        if not self.colormap_cache:
            return None
        
        # Find least recently used colormap
        lru_key = min(self.access_times.keys(), 
                     key=lambda k: self.access_times[k])
        
        # Remove from cache
        colormap_data = self.colormap_cache.pop(lru_key)
        del self.access_times[lru_key]
        
        # Update memory usage
        self.memory_usage -= self._estimate_colormap_size(colormap_data)
        self.evictions += 1
        
        logger.debug(f"Evicted colormap '{lru_key}' from memory cache")
        return lru_key
    
    def _ensure_memory_limit(self):
        """Ensure memory usage stays within limits"""
        while (self._get_current_memory_mb() > self.max_memory_mb or 
               len(self.colormap_cache) > self.max_colormaps):
            evicted = self._evict_least_recently_used()
            if evicted is None:
                break
    
    def get_colormap(self, name: str) -> Optional[np.ndarray]:
        """Get colormap from cache"""
        with self._lock:
            if name in self.colormap_cache:
                self.access_times[name] = np.datetime64('now')
                self.cache_hits += 1
                return self.colormap_cache[name].copy()
            
            self.cache_misses += 1
            return None
    
    def store_colormap(self, name: str, colormap_data: np.ndarray):
        """Store colormap in cache"""
        with self._lock:
            # Remove existing entry if present
            if name in self.colormap_cache:
                existing = self.colormap_cache.pop(name)
                self.memory_usage -= self._estimate_colormap_size(existing)
            
            # Ensure memory limits
            self._ensure_memory_limit()
            
            # Store new colormap
            self.colormap_cache[name] = colormap_data.copy()
            self.access_times[name] = np.datetime64('now')
            self.memory_usage += self._estimate_colormap_size(colormap_data)
            
            logger.debug(f"Cached colormap '{name}' ({self._estimate_colormap_size(colormap_data)} bytes)")
    
    def preload_colormap(self, name: str, gradient_data: List[Tuple], gamma: float = 1.0):
        """Preload and cache a colormap"""
        if name in self.colormap_cache:
            return  # Already cached
        
        try:
            # Generate colormap data
            colormap_data = self._generate_colormap_data(gradient_data, gamma)
            self.store_colormap(name, colormap_data)
            logger.info(f"Preloaded colormap '{name}'")
        except Exception as e:
            logger.error(f"Failed to preload colormap '{name}': {e}")
    
    def _generate_colormap_data(self, gradient: List[Tuple], gamma: float) -> np.ndarray:
        """Generate numpy array colormap from gradient data"""
        # Implementation would depend on the specific gradient format
        # This is a placeholder for the actual generation logic
        colormap = np.zeros((256, 3), dtype=np.uint8)
        
        # Generate colormap from gradient points
        # (This would need to match the existing colormap generation logic)
        for i in range(256):
            # Interpolate gradient colors
            # Placeholder implementation
            colormap[i] = [i % 256, (i * 2) % 256, (i * 3) % 256]
        
        return colormap
    
    def clear_cache(self):
        """Clear all cached colormaps"""
        with self._lock:
            self.colormap_cache.clear()
            self.access_times.clear()
            self.memory_usage = 0
            gc.collect()
            logger.info("Colormap cache cleared")
    
    def get_statistics(self) -> Dict:
        """Get memory manager statistics"""
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'cached_colormaps': len(self.colormap_cache),
            'memory_usage_mb': self._get_current_memory_mb(),
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'hit_rate_percent': hit_rate,
            'evictions': self.evictions
        }


class OptimizedColormapLoader:
    """Optimized colormap loader with lazy loading and memory management"""
    
    def __init__(self, memory_manager: ColormapMemoryManager):
        self.memory_manager = memory_manager
        self.generation_queue = []
        self._lock = Lock()
    
    def load_colormap_lazy(self, name: str, gradient_data: List[Tuple], 
                          gamma: float = 1.0) -> np.ndarray:
        """Load colormap with lazy generation and caching"""
        # Try cache first
        cached = self.memory_manager.get_colormap(name)
        if cached is not None:
            return cached
        
        # Generate colormap if not cached
        colormap_data = self._generate_colormap_optimized(gradient_data, gamma)
        self.memory_manager.store_colormap(name, colormap_data)
        
        return colormap_data
    
    def _generate_colormap_optimized(self, gradient: List[Tuple], 
                                   gamma: float) -> np.ndarray:
        """Optimized colormap generation using numpy operations"""
        # Convert gradient to numpy arrays for faster processing
        if not gradient:
            # Default gradient if none provided
            return np.zeros((256, 3), dtype=np.uint8)
        
        # Extract gradient points and positions
        positions = []
        colors = []
        
        for point in gradient:
            if isinstance(point, tuple) and len(point) == 2:
                # (position, color) format
                pos, color = point
                positions.append(pos)
                colors.append(color)
            else:
                # Color only, evenly spaced
                positions.append(len(positions) / len(gradient))
                colors.append(point)
        
        # Ensure positions are sorted
        if positions:
            sorted_indices = np.argsort(positions)
            positions = [positions[i] for i in sorted_indices]
            colors = [colors[i] for i in sorted_indices]
        
        # Generate colormap using numpy interpolation
        colormap = np.zeros((256, 3), dtype=np.uint8)
        
        if len(colors) >= 2:
            # Use numpy interpolation for smooth gradients
            for i in range(256):
                # Find position in gradient
                pos = i / 255.0
                
                # Find gradient segment
                segment_idx = 0
                while segment_idx < len(positions) - 1 and positions[segment_idx + 1] < pos:
                    segment_idx += 1
                
                if segment_idx >= len(positions) - 1:
                    # Use last color
                    color = colors[-1]
                else:
                    # Interpolate between colors
                    pos1, pos2 = positions[segment_idx], positions[segment_idx + 1]
                    color1, color2 = colors[segment_idx], colors[segment_idx + 1]
                    
                    if pos2 > pos1:
                        ratio = (pos - pos1) / (pos2 - pos1)
                        color = [
                            int(color1[j] * (1 - ratio) + color2[j] * ratio)
                            for j in range(3)
                        ]
                    else:
                        color = color1
                
                # Apply gamma correction
                if gamma != 1.0:
                    color = [int(pow(c / 255.0, 1.0 / gamma) * 255) for c in color]
                
                colormap[i] = [max(0, min(255, c)) for c in color]
        
        return colormap
    
    def preload_common_colormaps(self, gradient_dict: Dict[str, List[Tuple]]):
        """Preload commonly used colormaps"""
        common_colormaps = ['Rainbow', 'Rainbow-FastLED', 'Ocean', 'Fire']
        
        for name in common_colormaps:
            if name in gradient_dict:
                self.memory_manager.preload_colormap(name, gradient_dict[name])


# Global instances
_memory_manager = ColormapMemoryManager()
_colormap_loader = OptimizedColormapLoader(_memory_manager)


def get_memory_manager() -> ColormapMemoryManager:
    """Get the global colormap memory manager"""
    return _memory_manager


def get_colormap_loader() -> OptimizedColormapLoader:
    """Get the global colormap loader"""
    return _colormap_loader


def optimize_colormap_access(colormap_func):
    """Decorator to optimize colormap access functions"""
    def wrapper(*args, **kwargs):
        loader = get_colormap_loader()
        # Intercept colormap generation calls and route through optimizer
        if 'name' in kwargs and 'gradient' in kwargs:
            return loader.load_colormap_lazy(
                kwargs['name'], 
                kwargs['gradient'], 
                kwargs.get('gamma', 1.0)
            )
        return colormap_func(*args, **kwargs)
    return wrapper


@lru_cache(maxsize=32)
def cached_gamma_correction(value: float, gamma: float) -> float:
    """Cached gamma correction for performance"""
    if gamma == 1.0:
        return value
    return pow(value / 255.0, 1.0 / gamma) * 255


def get_colormap_statistics() -> Dict:
    """Get comprehensive colormap statistics"""
    return get_memory_manager().get_statistics()


def cleanup_colormap_memory():
    """Force cleanup of colormap memory"""
    get_memory_manager().clear_cache()
    gc.collect()
    logger.info("Colormap memory cleanup completed")
