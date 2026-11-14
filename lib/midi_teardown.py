"""Bound the caller's wait without abandoning ownership of a native MIDI handle.

Python cannot cancel a blocked native call. A daemon cleanup owner therefore
keeps the handle alive until that call returns. Repeated requests share the same
attempt; only a completed, unsuccessful attempt can be retried.

A finite Python wait assumes that the native backend releases the GIL while
blocked. A backend holding the GIL can suspend all Python threads; isolating that
backend in another process is required for a stronger caller-deadline guarantee.
"""
import logging
import threading
import time
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)


@dataclass
class _Attempt:
    done: threading.Event = field(default_factory=threading.Event)
    succeeded: bool = False
    error: Exception | None = None
    thread: threading.Thread | None = None


class MidiTeardown:
    def __init__(self, cleanup, *, name):
        self._cleanup = cleanup
        self._name = name
        self._lock = threading.Lock()
        self._attempt = None

    @property
    def status(self):
        with self._lock:
            attempt = self._attempt
            return {
                'pending': attempt is not None and not attempt.done.is_set(),
                'complete': attempt is not None and attempt.done.is_set() and attempt.succeeded,
                'error': str(attempt.error) if attempt is not None and attempt.error is not None else None,
            }

    def start(self):
        with self._lock:
            attempt = self._attempt
            if attempt is None or (attempt.done.is_set() and not attempt.succeeded):
                attempt = _Attempt()
                attempt.thread = threading.Thread(
                    target=self._run, args=(attempt,), name=self._name, daemon=True,
                )
                self._attempt = attempt
                try:
                    attempt.thread.start()
                except RuntimeError as error:
                    attempt.error = error
                    attempt.done.set()
            return attempt

    def _run(self, attempt):
        try:
            attempt.succeeded = self._cleanup() is not False
        except Exception as error:
            attempt.error = error
            _logger.exception('MIDI cleanup failed: %s', self._name)
        finally:
            attempt.done.set()

    def close(self, timeout=2):
        """Wait once against a global budget; False retains the cleanup owner.

        ``None`` is reserved for another daemon owner that must wait for this
        owner before taking over its resource. Normal callers use a finite budget.
        """
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        attempt = self.start()
        if threading.current_thread() is attempt.thread:
            return False
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        return attempt.done.wait(remaining) and attempt.succeeded

    @property
    def is_owner_thread(self):
        with self._lock:
            return self._attempt is not None and self._attempt.thread is threading.current_thread()

    def wait_done(self, timeout=None):
        """Wait for an existing owner without starting or retrying its action."""
        with self._lock:
            attempt = self._attempt
        if attempt is None:
            return True
        if attempt.thread is threading.current_thread():
            return False
        return attempt.done.wait(timeout)
