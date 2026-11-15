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
    assert monitor._stalls[0]['schedstat_previous']['observed'] == 10
    assert monitor._stalls[0]['schedstat_previous']['main_schedstat'] == counters


@pytest.mark.parametrize('available', [True, False])
def test_stall_uses_recent_periodic_sample_and_keeps_it_before_refresh(monkeypatch, available):
    monitor = RuntimeStallMonitor(interval=.01, threshold=.03, limit=2)
    # Normal wakes cross the 50 ms sampling boundary, then two stalls occur.
    ticks = iter([10, 10, 10.02, 10.02, 10.051, 10.051, 10.07,
                  10.07, 10.12, 10.12, 10.18, 10.18])
    monkeypatch.setattr('lib.runtime_stalls.time.perf_counter', lambda: next(ticks))
    samples = [
        {'runtime_ns': 100 + i, 'run_delay_ns': 1000 + i * 100, 'timeslices': i}
        if available else None for i in range(8)
    ]
    read_schedstat = Mock(side_effect=samples)
    monkeypatch.setattr('lib.runtime_stalls.schedstat', read_schedstat)
    monitor._stop = Mock()
    monitor._stop.wait.side_effect = [False] * 5 + [True]

    monitor._run()

    assert read_schedstat.call_count == 8  # two threads, four samples
    assert monitor._stall_count == 2
    assert len(monitor._stalls) == 2
    assert monitor._stalls[0]['schedstat_previous'] == {
        'observed': 10.051, 'main_schedstat': samples[2], 'canary_schedstat': samples[3],
    }
    stall = monitor._stalls[1]
    assert stall['observed'] == 10.18
    assert stall['schedstat_previous'] == {
        'observed': 10.12, 'main_schedstat': samples[4], 'canary_schedstat': samples[5],
    }
    assert stall['main_schedstat'] == samples[6]
    assert stall['canary_schedstat'] == samples[7]
