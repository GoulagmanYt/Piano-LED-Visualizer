import threading
from collections import deque


class BroadcastOutbox:
    """Thread-safe bounded outbox drained by the WebSocket event loop."""

    def __init__(self, maxlen=4096):
        self._items = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.dropped = 0

    def append(self, item):
        with self._lock:
            if self._items.maxlen is not None and len(self._items) >= self._items.maxlen:
                self.dropped += 1
            self._items.append(item)

    def drain(self):
        with self._lock:
            items = list(self._items)
            self._items.clear()
        return items

    def clear(self):
        with self._lock:
            self._items.clear()

    def __len__(self):
        with self._lock:
            return len(self._items)
