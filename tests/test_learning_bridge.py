import subprocess
import time
from types import SimpleNamespace
from unittest.mock import Mock

import mido
import pytest

from lib.learning_bridge import LearningBridge, resolve_unique, verify_no_direct_links
from lib.midi_queues import MidiQueues

PI = 'Piano:Keys 20:0'
PO = 'Piano:Keys 20:0'
CI = 'rtpmidid:Computer 30:0'
CO = 'rtpmidid:Computer 30:0'


class Settings:
    def get_setting_value(self, key):
        return dict(learning_piano_input=PI, learning_piano_output=PO,
                    learning_computer_input=CI, learning_computer_output=CO,
                    learning_block_control='1')[key]


class FakeInput:
    def __init__(self, callback):
        self.callback = callback
        self.closed = False
    def close(self):
        self.closed = True


class FakeOutput:
    def __init__(self):
        self.events = []
        self.closed = False
    def send(self, msg):
        self.events.append(msg)
    def close(self):
        self.closed = True


def wait(condition):
    deadline = time.monotonic() + 1
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(.001)


def test_full_duplex_bridge_routes_and_releases_old_ports():
    inputs = {}
    outputs = {}
    def open_input(name, callback):
        inputs[name] = FakeInput(callback)
        return inputs[name]
    def open_output(name):
        outputs[name] = FakeOutput()
        return outputs[name]
    queues = MidiQueues()
    bridge = LearningBridge(queues, Settings(), open_input=open_input, open_output=open_output,
                            verify_links=lambda *names: None)
    bridge.reconcile([PI, CI], [PO, CO])
    assert bridge.status == 'connected'
    inputs[CI].callback(mido.Message('note_on', note=60, channel=1, velocity=1))
    inputs[PI].callback(mido.Message('note_on', note=60, velocity=100))
    inputs[CI].callback(mido.Message('note_on', note=64, channel=2, velocity=90))
    assert queues.drain_guides()[0][0].note == 60
    assert queues.drain_live_for_learning()[0][0].note == 60
    wait(lambda: len(outputs[PO].events) == 1 and len(outputs[CO].events) == 1)
    assert bridge.close()
    assert inputs[PI].closed and inputs[CI].closed
    assert outputs[PO].closed and outputs[CO].closed
    assert outputs[PO].events[-1].type == 'note_off' and outputs[PO].events[-1].note == 64
    assert outputs[CO].events[-1].type == 'note_off' and outputs[CO].events[-1].note == 60
    assert queues.drain_guides()[0][0] is None


def test_bridge_fails_closed_on_missing_or_ambiguous_ports():
    opener = Mock()
    bridge = LearningBridge(MidiQueues(), Settings(), open_input=opener, open_output=opener,
                            verify_links=lambda *names: None)
    bridge.reconcile([PI], [PO, CO])
    assert bridge.status == 'waiting for all configured ports'
    opener.assert_not_called()
    assert resolve_unique('Piano:Keys 20:0', ['Piano:Keys 21:0', 'Piano:Keys 22:0']) is None


def test_direct_alsa_subscription_blocks_bridge(monkeypatch):
    graph = "client 20: 'Piano'\n    0 'Keys'\n\tConnecting To: 30:0\nclient 30: 'PC'\n    0 'Network'\n"
    monkeypatch.setattr('lib.learning_bridge.subprocess.run', lambda *a, **kw: subprocess.CompletedProcess([], 0, graph, ''))
    with pytest.raises(ValueError, match='Direct'):
        verify_no_direct_links(PI, PO, CI, CO)
    with pytest.raises(ValueError, match='distinct'):
        verify_no_direct_links(PI, PO, PI, PO)


def test_input_disconnect_reconnect_does_not_replay_old_notes():
    ins, outs = {}, []
    def open_in(name, callback):
        ins[name] = FakeInput(callback)
        return ins[name]
    def open_out(name):
        port = FakeOutput(); outs.append(port); return port
    bridge = LearningBridge(MidiQueues(), Settings(), open_input=open_in, open_output=open_out,
                            verify_links=lambda *names: None)
    bridge.reconcile([PI, CI], [PO, CO])
    ins[CI].callback(mido.Message('note_on', note=66, velocity=80))
    wait(lambda: bool(outs[0].events))
    bridge.reconcile([PI], [PO, CO])
    assert outs[0].closed and outs[0].events[-1].type == 'note_off'
    bridge.reconcile([PI, CI], [PO, CO])
    assert bridge.status == 'connected' and len(outs) == 4
    assert outs[2].events == []
    assert bridge.close()


def test_configuration_is_snapshot_until_restart():
    class MutableSettings(Settings):
        def __init__(self):
            self.changed = False
        def get_setting_value(self, key):
            if self.changed and key == 'learning_computer_input':
                return 'Other:Port 40:0'
            return super().get_setting_value(key)
    settings = MutableSettings()
    bridge = LearningBridge(MidiQueues(), settings,
                            open_input=lambda name, callback: FakeInput(callback),
                            open_output=lambda name: FakeOutput(), verify_links=lambda *names: None)
    bridge.reconcile([PI, CI], [PO, CO])
    assert bridge.status == 'connected'
    settings.changed = True
    bridge.reconcile([PI, CI], [PO, CO])
    assert bridge.status == 'connected'
    assert bridge._names == (PI, PO, CI, CO)
    assert bridge.close()


def test_piano_notes_reach_practice_without_leaking_guides():
    ins = {}
    def open_in(name, callback):
        ins[name] = FakeInput(callback)
        return ins[name]
    queues = MidiQueues()
    bridge = LearningBridge(queues, Settings(), open_input=open_in,
                            open_output=lambda name: FakeOutput(),
                            verify_links=lambda *names: None, practice_active=lambda: True)
    bridge.reconcile([PI, CI], [PO, CO])
    ins[PI].callback(mido.Message('note_on', note=60, velocity=80))
    ins[CI].callback(mido.Message('note_on', note=64, channel=1, velocity=1))
    assert queues.pop_websocket_publish()[0].note == 60
    assert queues.pop_websocket_publish() is None
    assert bridge.close()


def test_legacy_callback_is_fail_closed_when_bridge_enabled():
    from lib.midiports import MidiPorts
    ports = MidiPorts.__new__(MidiPorts)
    ports.learning_bridge_enabled = True
    ports.queues = MidiQueues()
    ports.msg_callback(mido.Message('note_on', note=60, velocity=100))
    assert not ports.queues.live_visualizer_queue
    assert not ports.queues.live_forward_queue


def test_bridge_does_not_reopen_while_an_output_worker_is_stuck():
    import threading
    entered = threading.Event()
    release = threading.Event()
    ins = {}
    outputs = []
    class BlockingOutput(FakeOutput):
        def send(self, msg):
            if msg.type == 'note_on':
                entered.set()
                release.wait(5)
            super().send(msg)
    def input_factory(name, callback):
        ins[name] = FakeInput(callback)
        return ins[name]
    def output_factory(name):
        output = BlockingOutput() if name == PO else FakeOutput()
        outputs.append(output)
        return output
    bridge = LearningBridge(MidiQueues(), Settings(), open_input=input_factory,
                            open_output=output_factory, verify_links=lambda *names: None)
    bridge.reconcile([PI, CI], [PO, CO])
    ins[CI].callback(mido.Message('note_on', note=60, velocity=100))
    assert entered.wait(1)
    bridge.reconcile([PI], [PO, CO])
    assert 'timed out' in bridge.status
    assert len(outputs) == 2 and not outputs[0].closed
    release.set()
    wait(lambda: outputs[0].closed)
    bridge.reconcile([PI, CI], [PO, CO])
    assert bridge.status == 'connected' and len(outputs) == 4
    assert bridge.close()
