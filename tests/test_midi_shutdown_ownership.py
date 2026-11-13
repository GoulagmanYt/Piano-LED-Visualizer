import threading
from unittest.mock import Mock

import mido
import pytest

from lib.midi_queues import MidiQueues
from lib.midiports import MidiPorts


def make_ports():
    ports = MidiPorts.__new__(MidiPorts)
    ports.queues = MidiQueues()
    ports.worker_running = True
    ports.monitor_running = True
    ports.monitor_stop = threading.Event()
    ports.midi_monitor_thread = None
    ports.live_forward_thread = None
    ports.websocket_publish_thread = None
    ports._output_lock = threading.RLock()
    ports._notify_forward_worker = Mock()
    ports._wake_websocket_publish_worker = Mock()
    ports.inport = Mock()
    ports.playport = Mock()
    return ports


def test_shutdown_retains_output_until_blocked_sender_exits(monkeypatch):
    ports = make_ports()
    port = ports.playport
    entered, release = threading.Event(), threading.Event()

    def send(_message):
        entered.set()
        assert release.wait(3)

    port.send.side_effect = send

    def forward():
        with ports._output_lock:
            port.send(mido.Message('note_on', note=60))

    worker = threading.Thread(target=forward)
    ports.live_forward_thread = worker
    worker.start()
    assert entered.wait(1)
    original_join = worker.join
    monkeypatch.setattr(worker, 'join', lambda timeout=None: original_join(timeout=0))
    try:
        assert ports.close() is False
        port.close.assert_not_called()
        assert port.send.call_count == 1
        assert ports.playport is port
    finally:
        release.set()
        original_join(timeout=1)
    assert ports.close() is True
    port.close.assert_called_once()


def test_shutdown_preserves_input_handle_after_drain_timeout():
    ports = make_ports()
    input_port = ports.inport
    output_port = ports.playport
    input_port.close.side_effect = [RuntimeError('input drain did not stop'), None]

    assert ports.close() is False
    assert ports.inport is input_port
    output_port.close.assert_not_called()
    assert ports.close() is True
    assert ports.inport is None
    output_port.close.assert_called_once()
    assert ports.playport is None


@pytest.mark.parametrize('owner', ['monitor', 'output_lock'])
def test_shutdown_retains_ports_while_other_native_owner_is_busy(owner, monkeypatch):
    ports = make_ports()
    port = ports.playport
    entered, release = threading.Event(), threading.Event()

    def own_native_resource():
        if owner == 'output_lock':
            ports._output_lock.acquire()
        entered.set()
        release.wait(3)
        if owner == 'output_lock':
            ports._output_lock.release()

    worker = threading.Thread(target=own_native_resource)
    worker.start()
    assert entered.wait(1)
    if owner == 'monitor':
        ports.midi_monitor_thread = worker
        original_join = worker.join
        monkeypatch.setattr(worker, 'join', lambda timeout=None: original_join(timeout=0))
    try:
        assert ports.close() is False
        port.close.assert_not_called()
        port.send.assert_not_called()
        ports.inport.close.assert_not_called()
    finally:
        release.set()
        threading.Thread.join(worker, timeout=1)
    assert ports.close() is True
    port.close.assert_called_once()
