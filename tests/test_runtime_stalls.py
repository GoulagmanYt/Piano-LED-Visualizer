import gc
from unittest.mock import Mock

import pytest

from lib.runtime_stalls import RuntimeStallMonitor


def test_gc_records_generation_and_duration_with_bounded_storage(monkeypatch):
    monitor = RuntimeStallMonitor(limit=1)
    ticks = iter([10, 10.062, 11, 11.001])
    monkeypatch.setattr('lib.runtime_stalls.time.perf_counter', lambda: next(ticks))
    monitor._gc_callback('start', {'generation': 0})
    monitor._gc_callback('stop', {'generation': 0, 'collected': 3})
    assert monitor._gc[0]['duration_ms'] == pytest.approx(62)
    monitor._gc_callback('start', {'generation': 2})
    monitor._gc_callback('stop', {'generation': 2, 'collected': 0})
    assert monitor._gc_count == 2
    assert len(monitor._gc) == 1
    assert monitor._gc[0]['generation'] == 2


def test_monitor_removes_callback_and_stops_without_changing_gc_policy():
    thresholds = gc.get_threshold()
    callbacks = list(gc.callbacks)
    monitor = RuntimeStallMonitor().start()
    try:
        assert monitor._gc_callback in gc.callbacks
    finally:
        monitor.close()
    assert not monitor._thread.is_alive()
    assert gc.callbacks == callbacks
    assert gc.get_threshold() == thresholds
    assert monitor.snapshot()['sample_limit'] == 1024
    monitor.close()


def test_canary_records_a_late_wakeup_with_scheduler_counters(monkeypatch):
    monitor = RuntimeStallMonitor()
    ticks = iter([10, 10, 10.010, 10.010])
    monkeypatch.setattr('lib.runtime_stalls.time.perf_counter', lambda: next(ticks))
    counters = {'runtime_ns': 1, 'run_delay_ns': 9_000_000, 'timeslices': 2}
    monkeypatch.setattr('lib.runtime_stalls.schedstat', lambda tid: counters)
    monitor._stop = Mock()
    monitor._stop.wait.side_effect = [False, True]
    monitor._run()
    assert monitor._stall_count == 1
    assert monitor._stalls[0]['lateness_ms'] == pytest.approx(9)
    assert monitor._stalls[0]['main_schedstat']['run_delay_ns'] == 9_000_000
