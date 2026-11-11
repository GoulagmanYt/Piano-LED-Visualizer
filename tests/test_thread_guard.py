#!/usr/bin/env python3

import threading

import thread_guard


def test_detects_a_thread_that_outlives_its_test():
    before = thread_guard.snapshot()
    release = threading.Event()
    worker = threading.Thread(target=release.wait, name="leaky", daemon=True)
    worker.start()
    try:
        leaked = thread_guard.new_live_threads(before)
        assert leaked == [worker]
        assert thread_guard.wait_for_exit(leaked, grace_s=0.05) == [worker]
        assert thread_guard.describe(leaked) == "leaky (daemon=True)"
    finally:
        release.set()
        worker.join(timeout=2)


def test_finished_threads_are_not_reported():
    before = thread_guard.snapshot()
    worker = threading.Thread(target=lambda: None)
    worker.start()
    worker.join()

    assert thread_guard.new_live_threads(before) == []


def test_slow_but_finishing_threads_get_a_grace_period():
    before = thread_guard.snapshot()
    release = threading.Event()
    worker = threading.Thread(target=release.wait, daemon=True)
    worker.start()
    threading.Timer(0.05, release.set).start()

    survivors = thread_guard.wait_for_exit(thread_guard.new_live_threads(before), grace_s=2.0)

    assert survivors == []
