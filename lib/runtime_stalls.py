"""Opt-in, bounded evidence for GC and scheduler stalls; no policy changes."""
import gc
import threading
import time
from collections import deque
from pathlib import Path


def schedstat(tid):
    try:
        values = Path(f'/proc/self/task/{tid}/schedstat').read_text().split()
        return {'runtime_ns': int(values[0]), 'run_delay_ns': int(values[1]),
                    'timeslices': int(values[2])}
    except (OSError, ValueError, IndexError):
        return None


class RuntimeStallMonitor:
    def __init__(self, interval=.001, threshold=.005, limit=1024):
        if interval <= 0 or threshold <= 0 or limit < 1:
            raise ValueError('Invalid stall monitor parameters')
        self.interval = interval
        self.threshold = threshold
        self._gc = deque(maxlen=limit)
        self._stalls = deque(maxlen=limit)
        self._gc_started = {}
        self._stop = threading.Event()
        self._thread = None
        self._main_tid = threading.main_thread().native_id
        self._gc_count = self._stall_count = 0
        self._sched_start = None

    def _gc_callback(self, phase, info):
        now = time.perf_counter()
        generation = info['generation']
        if phase == 'start':
            self._gc_started[generation] = now
        elif phase == 'stop':
            started = self._gc_started.pop(generation, now)
            self._gc_count += 1
            self._gc.append({'start': started, 'end': now, 'generation': generation,
                                 'duration_ms': (now - started) * 1000,
                                 'collected': info.get('collected', 0)})

    def start(self):
        if self._thread is not None:
            raise RuntimeError('Stall monitor already started')
        self._sched_start = schedstat(self._main_tid)
        gc.callbacks.append(self._gc_callback)
        self._thread = threading.Thread(target=self._run, name='latency-canary', daemon=True)
        self._thread.start()
        return self

    def _run(self):
        deadline = time.perf_counter() + self.interval
        while not self._stop.wait(max(0, deadline - time.perf_counter())):
            now = time.perf_counter()
            if now - deadline > self.threshold:
                self._stall_count += 1
                self._stalls.append({'expected': deadline, 'observed': now,
                                         'lateness_ms': (now - deadline) * 1000,
                                         'main_schedstat': schedstat(self._main_tid),
                                         'canary_schedstat': schedstat(threading.get_native_id())})
            deadline = now + self.interval

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
            if self._thread.is_alive():
                raise RuntimeError('Stall monitor did not stop')
        if self._gc_callback in gc.callbacks:
            gc.callbacks.remove(self._gc_callback)

    def snapshot(self):
        return {'clock': 'perf_counter seconds', 'gc_thresholds': gc.get_threshold(),
                    'gc_count': self._gc_count, 'stall_count': self._stall_count,
                    'sample_limit': self._gc.maxlen, 'gc': list(self._gc.copy()), 'stalls': list(self._stalls.copy()),
                    'main_schedstat_start': self._sched_start,
                    'main_schedstat_end': schedstat(self._main_tid)}
