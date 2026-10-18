import threading

from lib.runtime_diagnostics import RuntimeDiagnostics


def test_hot_metrics_do_not_wait_for_unrelated_ui_metadata_lock():
    diagnostics = RuntimeDiagnostics()
    warm, go, done = threading.Event(), threading.Event(), threading.Event()

    def midi_worker():
        diagnostics.record_duration('send', .001)
        diagnostics.increment_counter('sent')
        warm.set()
        go.wait(2)
        diagnostics.record_duration('send', .003)
        diagnostics.increment_counter('sent')
        done.set()

    worker = threading.Thread(target=midi_worker)
    try:
        worker.start()
        assert warm.wait(1)
        with diagnostics._lock:
            go.set()
            assert done.wait(.25), 'MIDI hot metrics blocked behind UI diagnostics'
    finally:
        go.set()
        worker.join(2)
    report = diagnostics.snapshot()
    assert report['counters']['sent'] == 2
    assert report['timings']['send']['avg_ms'] == 2.0


def test_thread_metrics_merge_counts_max_and_latest_value_and_reset_live_workers():
    diagnostics = RuntimeDiagnostics()
    first_done, second_done, after_reset = (threading.Event() for _ in range(3))

    def worker():
        for _ in range(1000):
            diagnostics.record_duration('send', .001)
            diagnostics.increment_counter('sent', 2)
        first_done.set()
        second_done.wait(2)
        diagnostics.record_duration('send', .003)
        diagnostics.increment_counter('sent')
        after_reset.set()

    thread = threading.Thread(target=worker)
    try:
        thread.start()
        assert first_done.wait(1)
        diagnostics.record_duration('send', .005)
        diagnostics.increment_counter('sent', 5)
        before = diagnostics.snapshot()
        assert before['counters']['sent'] == 2005
        assert before['timings']['send']['count'] == 1001
        assert before['timings']['send']['max_ms'] == 5.0
        assert before['timings']['send']['last_ms'] == 5.0
        diagnostics.reset()
        second_done.set()
        assert after_reset.wait(1)
        final = diagnostics.snapshot()
        assert final['counters']['sent'] == 1
        assert final['timings']['send']['count'] == 1
        assert final['timings']['send']['last_ms'] == 3.0
    finally:
        second_done.set()
        thread.join(2)
