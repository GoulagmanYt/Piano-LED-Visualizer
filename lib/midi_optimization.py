"""
MIDI processing optimizations - Performance improvements for MIDI event handling
"""
import time
from collections import deque
from threading import Lock
from lib.log_setup import logger


class MIDIMessagePool:
    """Pool for reusing MIDI message objects to reduce garbage collection"""
    
    def __init__(self, initial_size=100):
        self._pool = deque()
        self._lock = Lock()
        self._created_count = 0
        
        # Pre-allocate some objects
        for _ in range(initial_size):
            self._pool.append(self._create_message_object())
    
    def _create_message_object(self):
        """Create a new message object"""
        self._created_count += 1
        return {
            'type': None,
            'note': None,
            'velocity': None,
            'control': None,
            'value': None,
            'timestamp': 0,
            'is_meta': False,
            '_in_use': False
        }
    
    def get_message(self):
        """Get a message object from the pool"""
        with self._lock:
            if self._pool:
                msg = self._pool.popleft()
                msg['_in_use'] = True
                return msg
            else:
                # Pool exhausted, create new object
                return self._create_message_object()
    
    def return_message(self, msg):
        """Return a message object to the pool"""
        if msg and hasattr(msg, '_in_use') and msg['_in_use']:
            with self._lock:
                # Reset message data
                msg['type'] = None
                msg['note'] = None
                msg['velocity'] = None
                msg['control'] = None
                msg['value'] = None
                msg['timestamp'] = 0
                msg['is_meta'] = False
                msg['_in_use'] = False
                
                self._pool.append(msg)
    
    def get_stats(self):
        """Get pool statistics"""
        with self._lock:
            return {
                'pool_size': len(self._pool),
                'created_count': self._created_count
            }


class MIDIEventBatch:
    """Batch processor for MIDI events to reduce per-event overhead"""
    
    def __init__(self, max_batch_size=50, max_time_ms=5):
        self.max_batch_size = max_batch_size
        self.max_time_ms = max_time_ms
        self.batch = []
        self.batch_start_time = 0
        self.message_pool = MIDIMessagePool()
    
    def add_event(self, midi_msg, timestamp):
        """Add an event to the current batch"""
        self.batch.append((midi_msg, timestamp))
        
        # Check if batch should be processed
        if len(self.batch) >= self.max_batch_size:
            return True
        
        # Check time limit
        if self.batch_start_time == 0:
            self.batch_start_time = time.perf_counter()
        elif (time.perf_counter() - self.batch_start_time) * 1000 >= self.max_time_ms:
            return True
        
        return False
    
    def get_batch(self):
        """Get and clear the current batch"""
        batch = self.batch.copy()
        self.batch.clear()
        self.batch_start_time = 0
        return batch
    
    def is_empty(self):
        """Check if batch is empty"""
        return len(self.batch) == 0


class MIDIPerformanceMonitor:
    """Monitor MIDI processing performance"""
    
    def __init__(self, window_size=100):
        self.window_size = window_size
        self.processing_times = deque(maxlen=window_size)
        self.event_counts = deque(maxlen=window_size)
        self.last_log_time = 0
        self.total_events = 0
        self.start_time = time.perf_counter()
    
    def record_processing(self, processing_time, event_count):
        """Record processing metrics"""
        self.processing_times.append(processing_time)
        self.event_counts.append(event_count)
        self.total_events += event_count
    
    def get_average_processing_time(self):
        """Get average processing time"""
        if not self.processing_times:
            return 0
        return sum(self.processing_times) / len(self.processing_times)
    
    def get_events_per_second(self):
        """Get current events per second rate"""
        elapsed = time.perf_counter() - self.start_time
        if elapsed > 0:
            return self.total_events / elapsed
        return 0
    
    def should_log_stats(self, interval_seconds=30):
        """Check if stats should be logged"""
        now = time.perf_counter()
        if now - self.last_log_time >= interval_seconds:
            self.last_log_time = now
            return True
        return False
    
    def get_stats_summary(self):
        """Get comprehensive stats summary"""
        return {
            'avg_processing_time_ms': self.get_average_processing_time() * 1000,
            'events_per_second': self.get_events_per_second(),
            'total_events': self.total_events,
            'uptime_seconds': time.perf_counter() - self.start_time
        }


# Global instances
_midi_batch = MIDIEventBatch()
_performance_monitor = MIDIPerformanceMonitor()


def get_midi_batch():
    """Get global MIDI batch processor"""
    return _midi_batch


def get_performance_monitor():
    """Get global performance monitor"""
    return _performance_monitor


def optimize_midi_queue_processing(midi_queue, max_events_per_frame=20):
    """
    Optimized MIDI queue processing with bounded processing time.
    
    Args:
        midi_queue: MIDI message queue
        max_events_per_frame: Maximum events to process per frame
        
    Returns:
        tuple: (processed_events, processing_time)
    """
    start_time = time.perf_counter()
    processed = 0
    
    # Process events in batches for better cache locality
    batch = []
    
    while processed < max_events_per_frame and midi_queue:
        try:
            msg, timestamp = midi_queue.popleft()
            batch.append((msg, timestamp))
            processed += 1
        except IndexError:
            break
    
    processing_time = time.perf_counter() - start_time
    
    # Record performance metrics
    _performance_monitor.record_processing(processing_time, processed)
    
    return batch, processing_time


def log_midi_performance_if_needed():
    """Log MIDI performance stats if interval has passed"""
    if _performance_monitor.should_log_stats():
        stats = _performance_monitor.get_stats_summary()
        logger.info(f"[MIDI Performance] {stats['events_per_second']:.1f} events/sec, "
                   f"Avg processing: {stats['avg_processing_time_ms']:.3f}ms")
