"""One ordered MIDI output worker for a single Learning-mode port generation.

The worker owns the port until it has sent every queued event and closed it.
No callback or reconnect thread may close or reuse this port concurrently. A
failed send makes the generation unusable and discards its remaining queue;
callers must create a new worker/port rather than replaying stale notes.
"""
import queue
import threading

import mido

from lib.midi_teardown import MidiTeardown

_STOP = object()


class LearningOutput:
    def __init__(self, port):
        self._port = port
        self._queue = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._accepting = True
        self._failure = None
        self._thread = threading.Thread(target=self._run, name='learning-midi-output', daemon=True)
        self._teardown = MidiTeardown(self._cleanup_native, name='learning-output-cleanup')
        self._thread.start()

    @property
    def finished(self):
        return self._teardown.status['complete']

    @property
    def shutdown_status(self):
        return self._teardown.status

    @property
    def failure(self):
        with self._lock:
            return self._failure

    def enqueue(self, message, timestamp=None):
        """Nonblocking sink for LearningSession; False means generation closed."""
        with self._lock:
            if not self._accepting:
                return False
            self._queue.put(message)
            return True

    def close(self, timeout=2):
        """Drain then close; False means timeout or a send/close failure.

        A timed-out worker retains ownership of its port. The caller must not
        close the underlying port or open its replacement until it finishes.
        """
        with self._lock:
            if self._accepting:
                self._accepting = False
                self._queue.put(_STOP)
        if threading.current_thread() is self._thread:
            self._teardown.start()
            return False
        if not self._teardown.close(timeout):
            return False
        return self.failure is None

    def _cleanup_native(self):
        self._thread.join()
        try:
            self._port.close()
        except Exception as error:
            self._mark_failure(error)
            raise

    def _mark_failure(self, error):
        with self._lock:
            self._accepting = False
            if self._failure is None:
                self._failure = error

    def _run(self):
        try:
            while True:
                msg = self._queue.get()
                if msg is _STOP:
                    break
                try:
                    self._port.send(msg)
                except Exception as error:
                    self._mark_failure(error)
                    while True:
                        try:
                            self._queue.get_nowait()
                        except queue.Empty:
                            break
                    # Best effort panic on the same worker/port; no stale queued
                    # note-ons are delivered after a failed send.
                    for channel in range(16):
                        try:
                            self._port.send(mido.Message('control_change', channel=channel, control=64, value=0))
                            self._port.send(mido.Message('control_change', channel=channel, control=123, value=0))
                            self._port.send(mido.Message('control_change', channel=channel, control=120, value=0))
                        except Exception:
                            break
                    break
        finally:
            self._teardown.start()
