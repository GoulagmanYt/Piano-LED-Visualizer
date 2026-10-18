from collections import deque
import threading
from unittest.mock import Mock

import mido
import pytest

from lib.buffered_midi_input import BufferedMidiInput, open_midi_input


class NativeInput:
    def __init__(self):
        self.events = deque()
        self.opened = None
        self.cleaned = False
        self.closed = False
        self.filters = None

    def get_ports(self):
        return ['USB:Port 16:0']

    def open_port(self, index):
        self.opened = index

    def open_virtual_port(self, name):
        self.opened = name

    def ignore_types(self, **kwargs):
        self.filters = kwargs

    def set_callback(self, *args):
        raise AssertionError('native input must never wait for a Python callback')

    def get_message(self):
        try:
            return self.events.popleft()
        except IndexError:
            return None

    def close_port(self):
        self.closed = True

    def delete(self):
        self.cleaned = True


def test_native_queue_preserves_burst_while_python_consumer_is_busy():
    native = NativeInput()
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    received = []
    expected = [mido.Message('note_on', note=n % 128, velocity=n % 127 + 1) for n in range(10000)]

    def receive(message):
        if not received:
            entered.set()
            assert release.wait(2)
        received.append(message)
        if len(received) == 10000:
            done.set()

    port = BufferedMidiInput('USB:Port 16:0', receive, native_input=native)
    try:
        native.events.append((expected[0].bytes(), .0))
        assert entered.wait(1)
        native.events.extend((msg.bytes(), .001) for msg in expected[1:])
        release.set()
        assert done.wait(2)
        assert received == expected
        assert native.opened == 0
        assert native.filters == dict(sysex=False, timing=True, active_sense=True)
    finally:
        release.set()
        port.close()
    assert native.closed and native.cleaned
    assert port.closed


def test_virtual_input_and_invalid_midi_do_not_break_following_notes():
    native = NativeInput()
    native.events.extend([([255, 255], .0), ([0x90, 60, 80], .001)])
    received, done = [], threading.Event()

    def receive(message):
        received.append(message)
        done.set()

    port = BufferedMidiInput('test', receive, virtual=True, native_input=native)
    try:
        assert done.wait(1)
        assert native.opened == 'test'
        assert received == [mido.Message('note_on', note=60, velocity=80)]
    finally:
        port.close()
        port.close()


def test_open_failure_releases_native_resources():
    native = NativeInput()
    with pytest.raises(OSError, match='unknown'):
        BufferedMidiInput('missing', lambda msg: None, native_input=native)
    assert native.closed and native.cleaned


def test_callback_failure_is_visible_and_resources_can_be_closed():
    native = NativeInput()
    native.events.append(([0x90, 60, 80], .0))
    port = BufferedMidiInput('USB:Port 16:0', Mock(side_effect=RuntimeError('consumer failed')),
                             native_input=native)
    port._thread.join(1)
    assert port.closed
    assert isinstance(port.error, RuntimeError)
    port.close()
    assert native.cleaned


def test_other_backend_keeps_mido_behavior(monkeypatch):
    monkeypatch.setattr('lib.buffered_midi_input.sys.platform', 'win32')
    opened = object()
    opener = Mock(return_value=opened)
    monkeypatch.setattr('lib.buffered_midi_input.mido.open_input', opener)
    callback = Mock()
    assert open_midi_input('device', callback=callback) is opened
    opener.assert_called_once_with('device', callback=callback, virtual=False)


def test_close_never_deletes_backend_while_consumer_is_inside_callback():
    native = NativeInput()
    native.events.append(([0x90, 60, 80], .0))
    entered, release = threading.Event(), threading.Event()

    def receive(message):
        entered.set()
        release.wait(5)

    port = BufferedMidiInput('USB:Port 16:0', receive, native_input=native)
    try:
        assert entered.wait(1)
        with pytest.raises(RuntimeError, match='refusing concurrent'):
            port.close()
        assert not native.cleaned
    finally:
        release.set()
        port.close()
    assert native.cleaned


def test_kernel_pool_is_sized_before_subscribing_to_incoming_notes(monkeypatch):
    sized = False

    def size_pool():
        nonlocal sized
        sized = True

    class Input(NativeInput):
        def open_port(self, index):
            assert sized, 'resizing an already subscribed ALSA FIFO discards incoming events'
            super().open_port(index)

    monkeypatch.setattr('lib.buffered_midi_input.enlarge_input_pools', size_pool)
    port = BufferedMidiInput('USB:Port 16:0', lambda msg: None, native_input=Input())
    port.close()


def test_optional_pool_tuning_failure_does_not_disable_working_input(monkeypatch):
    monkeypatch.setattr('lib.buffered_midi_input.enlarge_input_pools',
                        Mock(side_effect=OSError('pool tuning unavailable')))
    native = NativeInput()
    native.events.append(([0x90, 60, 80], .0))
    received, done = [], threading.Event()

    def receive(message):
        received.append(message)
        done.set()

    port = BufferedMidiInput('USB:Port 16:0', receive, native_input=native)
    try:
        assert done.wait(1)
        assert received == [mido.Message('note_on', note=60, velocity=80)]
    finally:
        port.close()
