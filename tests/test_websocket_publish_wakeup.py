#!/usr/bin/env python3
"""The websocket publish worker must wake up when a note is queued.

It used to poll with a fixed 10 ms sleep, adding up to 10 ms between a MIDI
note arriving and its echo being handed to the websocket broadcaster.
"""

import collections
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import mido
import pytest

sys.path.append("./")
sys.path.append("../")

import lib.midiports as midiports_module
from lib.midi_queues import MidiQueues
from lib.midiports import MidiPorts
from webinterface import app_state, webinterface

PLAY_PORT = "rtpmidid:OSCMidiRobin 128:3"


class DummySettings:
    def __init__(self, initial):
        self.values = dict(initial)

    def get_setting_value(self, name):
        return self.values.get(name)

    def change_setting_value(self, name, value):
        self.values[name] = value


class DummyPort:
    def close(self):
        pass

    def send(self, _msg):
        pass


def _note_on(note=60):
    return mido.Message("note_on", note=note, velocity=90)


@pytest.fixture
def midiports(monkeypatch):
    monkeypatch.setattr(MidiPorts, "start_background_workers", lambda self: None)
    settings = DummySettings({"input_port": "default", "play_port": PLAY_PORT})
    with patch("lib.midiports._get_cached_input_names", return_value=[]), patch(
        "lib.midiports._get_cached_output_names", return_value=[PLAY_PORT]
    ), patch("lib.midiports.mido.open_output", return_value=DummyPort()):
        return MidiPorts(settings)


@pytest.fixture
def published(monkeypatch):
    """Capture what the worker hands to the websocket broadcaster."""
    sink = collections.deque(maxlen=100000)
    monkeypatch.setattr(webinterface, "websocket_midi_send", sink)
    monkeypatch.setattr(app_state, "practice_active", True, raising=False)
    # A long idle timeout proves delivery comes from the wake-up, not the poll.
    monkeypatch.setattr(midiports_module, "WEBSOCKET_PUBLISH_IDLE_TIMEOUT_S", 5.0)
    return sink


def _start_worker(midiports):
    midiports.worker_running = True
    worker = threading.Thread(target=midiports._websocket_publish_loop, daemon=True)
    worker.start()
    return worker


def _stop_worker(midiports, worker):
    midiports.worker_running = False
    midiports._wake_websocket_publish_worker()
    worker.join(timeout=2)
    assert not worker.is_alive(), "worker did not stop promptly after being woken"


def _wait_for(predicate, timeout):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


def test_notes_set_the_publish_event_other_messages_do_not():
    queues = MidiQueues()

    queues.enqueue_all_live(mido.Message("pitchwheel", pitch=100), is_note=False)
    assert not queues.websocket_publish_event.is_set()

    queues.enqueue_all_live(_note_on(), is_note=True)
    assert queues.websocket_publish_event.is_set()


def test_enqueue_websocket_publish_sets_the_publish_event():
    queues = MidiQueues()

    assert queues.enqueue_websocket_publish(_note_on()) is True

    assert queues.websocket_publish_event.is_set()


def test_a_rejected_item_does_not_wake_the_worker():
    queues = MidiQueues(websocket_publish_maxlen=1)
    queues.enqueue_websocket_publish(_note_on())
    queues.websocket_publish_event.clear()

    assert queues.enqueue_websocket_publish(_note_on(61)) is False

    assert not queues.websocket_publish_event.is_set()


def test_note_is_published_without_waiting_for_the_idle_timeout(midiports, published):
    worker = _start_worker(midiports)
    try:
        time.sleep(0.05)  # let the worker go idle on its 5 s wait
        started = time.perf_counter()
        midiports.queues.enqueue_all_live(_note_on(), is_note=True)

        assert _wait_for(lambda: len(published) == 1, timeout=1.0), "note waited for the poll"
        assert time.perf_counter() - started < 0.5
        assert published[0].startswith("midi_event")
    finally:
        _stop_worker(midiports, worker)


def test_no_wakeup_is_lost_while_notes_keep_arriving(midiports, published):
    worker = _start_worker(midiports)
    try:
        total = 300
        for note in range(total):
            midiports.queues.enqueue_all_live(_note_on(30 + note % 60), is_note=True)
            time.sleep(0.0003)

        assert _wait_for(lambda: len(published) == total, timeout=2.0), (
            f"only {len(published)}/{total} notes published"
        )
    finally:
        _stop_worker(midiports, worker)


def test_close_wakes_an_idle_worker(midiports, published):
    worker = _start_worker(midiports)
    time.sleep(0.05)

    midiports.worker_running = False
    midiports._wake_websocket_publish_worker()
    worker.join(timeout=1.0)

    assert not worker.is_alive()


def test_worker_still_polls_when_the_queues_have_no_event(midiports):
    midiports.queues = SimpleNamespace()  # older/fake queue objects
    midiports.websocket_publish_queue = collections.deque()
    calls = []

    def flush_once():
        calls.append(1)
        midiports.worker_running = False
        return False

    midiports._flush_websocket_publish_queue_once = flush_once
    midiports.worker_running = True

    midiports._websocket_publish_loop()

    assert calls == [1]
