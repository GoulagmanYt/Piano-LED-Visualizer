"""Helpers to make sure a test does not leave worker threads behind.

A leaked daemon thread keeps running under the *next* test's patches (for
example a globally patched time.perf_counter), which produced intermittent
StopIteration warnings from MidiPorts workers.
"""

import threading
import time


def snapshot():
    return set(threading.enumerate())


def new_live_threads(before):
    return [t for t in threading.enumerate() if t not in before and t.is_alive()]


def wait_for_exit(threads, grace_s=2.0):
    """Give `threads` up to `grace_s` seconds to finish; return the survivors."""
    deadline = time.monotonic() + grace_s
    for thread in threads:
        remaining = deadline - time.monotonic()
        if remaining > 0:
            thread.join(remaining)
    return [t for t in threads if t.is_alive()]


def describe(threads):
    return ", ".join(f"{t.name} (daemon={t.daemon})" for t in threads)
