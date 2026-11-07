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


@pytest.mark.parametrize('channel', range(1, 13))
def test_bridge_separates_synthesia_guide_channels_from_piano_sound(channel):
    """Drive the real callbacks and workers, not just the router in isolation."""
    inputs, outputs = {}, {}
    def open_input(name, callback):
        inputs[name] = FakeInput(callback)
        return inputs[name]
    def open_output(name):
        outputs[name] = FakeOutput()
        return outputs[name]
    queues = MidiQueues()
    bridge = LearningBridge(queues, Settings(), open_input=open_input,
                            open_output=open_output, verify_links=lambda *args: None)
    try:
        bridge.reconcile([PI, CI], [PO, CO])
        inputs[CI].callback(mido.Message('note_on', note=60, channel=channel, velocity=1))
        inputs[CI].callback(mido.Message('note_on', note=60, channel=channel, velocity=90))
        inputs[CI].callback(mido.Message('note_on', note=60, channel=channel, velocity=0))
        inputs[CI].callback(mido.Message('note_off', note=60, channel=channel))
        guides = [msg for msg, _ in queues.drain_guides()]
        assert [(msg.type, msg.velocity) for msg in guides] == [('note_on', 1), ('note_off', 64)]
        wait(lambda: len(outputs[PO].events) == 2)
        assert [(msg.type, msg.velocity) for msg in outputs[PO].events] == [
            ('note_on', 90), ('note_on', 0)]
        assert outputs[CO].events == []
    finally:
        assert bridge.close()


def test_bridge_partial_chord_guides_and_echo_filter_end_to_end():
    inputs, outputs = {}, {}
    def open_input(name, callback):
        inputs[name] = FakeInput(callback)
        return inputs[name]
    def open_output(name):
        outputs[name] = FakeOutput()
        return outputs[name]
    queues = MidiQueues()
    bridge = LearningBridge(queues, Settings(), open_input=open_input,
                            open_output=open_output, verify_links=lambda *args: None)
    try:
        bridge.reconcile([PI, CI], [PO, CO])
        for note, channel in ((55, 1), (67, 10)):
            inputs[CI].callback(mido.Message('note_on', note=note, channel=channel, velocity=1))
        assert [msg.note for msg, _ in queues.drain_guides()] == [55, 67]
        inputs[PI].callback(mido.Message('note_on', note=67, velocity=80))
        inputs[CI].callback(mido.Message('note_on', note=67, velocity=80))  # echo
        inputs[CI].callback(mido.Message('note_off', note=67))  # partial chord
        assert queues.drain_guides() == []
        inputs[PI].callback(mido.Message('note_on', note=55, velocity=70))
        inputs[CI].callback(mido.Message('note_off', note=55))
        assert sorted(msg.note for msg, _ in queues.drain_guides()) == [55, 67]
        wait(lambda: len(outputs[CO].events) == 2)
        assert [msg.note for msg in outputs[CO].events] == [67, 55]
        assert outputs[PO].events == []
    finally:
        assert bridge.close()


def test_bridge_rtp_endpoint_disappearance_cleanup_and_return():
    """The port monitor must reconcile on endpoint loss before reporting recovery."""
    inputs, opened = {}, []
    def open_input(name, callback):
        inputs[name] = FakeInput(callback)
        return inputs[name]
    def open_output(name):
        port = FakeOutput()
        opened.append((name, port))
        return port
    queues = MidiQueues()
    bridge = LearningBridge(queues, Settings(), open_input=open_input,
                            open_output=open_output, verify_links=lambda *args: None)
    try:
        bridge.reconcile([PI, CI], [PO, CO])
        inputs[CI].callback(mido.Message('note_on', note=62, channel=2, velocity=80))
        inputs[PI].callback(mido.Message('control_change', control=64, value=127))
        inputs[PI].callback(mido.Message('note_on', note=60, velocity=80))
        wait(lambda: len(opened[0][1].events) >= 1 and len(opened[1][1].events) >= 2)
        bridge.reconcile([PI], [PO])
        assert bridge.status == 'waiting for all configured ports'
        assert all(port.closed for _, port in opened)
        assert any(msg.type == 'note_off' and msg.note == 62 for msg in opened[0][1].events)
        assert any(msg.type == 'note_off' and msg.note == 60 for msg in opened[1][1].events)
        assert any(msg.type == 'control_change' and msg.control == 64 and msg.value == 0
                   for msg in opened[1][1].events)
        assert any(msg is None for msg, _ in queues.drain_guides())
        bridge.reconcile([PI, CI], [PO, CO])
        assert bridge.status == 'connected'
        assert len(opened) == 4 and all(not port.events for _, port in opened[2:])
        inputs[PI].callback(mido.Message('note_on', note=65, velocity=85))
        wait(lambda: len(opened[3][1].events) == 1)
        assert opened[3][1].events[0].note == 65
    finally:
        assert bridge.close()
