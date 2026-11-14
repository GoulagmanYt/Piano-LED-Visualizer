import threading
import time
from unittest.mock import Mock

from lib.midi_teardown import MidiTeardown


def test_idle_cleanup_finishes_once_and_repeat_close_is_idempotent():
    cleanup = Mock()
    teardown = MidiTeardown(cleanup, name='test-midi-cleanup')
    assert teardown.close()
    assert teardown.close()
    cleanup.assert_called_once()
    assert teardown.status == {'pending': False, 'complete': True, 'error': None}


def test_concurrent_callers_share_one_blocked_cleanup_and_one_deadline():
    entered, release = threading.Event(), threading.Event()
    calls = []

    def cleanup():
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(5)

    teardown = MidiTeardown(cleanup, name='test-midi-cleanup')
    results = []
    callers = [threading.Thread(target=lambda: results.append(teardown.close(.02))) for _ in range(4)]
    started = time.monotonic()
    try:
        for caller in callers:
            caller.start()
        assert entered.wait(1)
        for caller in callers:
            caller.join(1)
        assert results == [False] * 4
        assert time.monotonic() - started < .5
        assert len(calls) == 1
        assert teardown.status['pending']
    finally:
        release.set()
        for caller in callers:
            caller.join(1)
        assert teardown.close(1)
    assert len(calls) == 1


def test_failed_cleanup_can_be_retried_without_repeating_successful_attempt():
    cleanup = Mock(side_effect=[OSError('native close failed'), None])
    teardown = MidiTeardown(cleanup, name='test-midi-cleanup')
    assert not teardown.close()
    assert teardown.status['error'] == 'native close failed'
    assert teardown.close()
    assert teardown.close()
    assert cleanup.call_count == 2


def test_cleanup_callback_can_request_close_without_waiting_for_itself():
    results = []
    teardown = MidiTeardown(lambda: results.append(teardown.close(1)), name='test-midi-cleanup')
    assert teardown.close(1)
    assert results == [False]


def test_cleanup_worker_start_failure_is_visible_and_retryable(monkeypatch):
    original_start = threading.Thread.start
    starts = 0

    def start(thread):
        nonlocal starts
        starts += 1
        if starts == 1:
            raise RuntimeError('cannot start new thread')
        return original_start(thread)

    monkeypatch.setattr(threading.Thread, 'start', start)
    cleanup = Mock()
    teardown = MidiTeardown(cleanup, name='test-midi-cleanup')
    assert not teardown.close()
    assert teardown.status['error'] == 'cannot start new thread'
    assert teardown.close()
    cleanup.assert_called_once()
