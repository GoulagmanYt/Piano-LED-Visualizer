import threading
import time
from collections import deque
from unittest.mock import Mock

import mido
import pytest

from lib.buffered_midi_input import BufferedMidiInput
from lib.learning_bridge import LearningBridge
from lib.learning_output import LearningOutput
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


@pytest.mark.parametrize('stage', ['send', 'panic', 'input_close', 'output_close'])
def test_port_shutdown_returns_while_native_owner_blocks_and_never_reopens(stage):
    ports = make_ports()
    port = ports.playport
    entered, release = threading.Event(), threading.Event()
    calls = []
    worker = None

    def block(*_args):
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(5)

    if stage == 'send':
        def send():
            with ports._output_lock:
                block()
        worker = threading.Thread(target=send)
        ports.live_forward_thread = worker
        worker.start()
        assert entered.wait(1)
    elif stage == 'panic':
        port.send.side_effect = block
    elif stage == 'input_close':
        ports.inport.close.side_effect = block
    else:
        port.close.side_effect = block
    try:
        started = time.monotonic()
        assert not ports.close(timeout=.02)
        assert time.monotonic() - started < .5
        assert entered.wait(1)
        assert not ports.close(timeout=.02)
        assert ports.shutdown_status['pending']
        assert len(set(calls)) == 1
        assert ports.playport is port
        if stage != 'output_close':
            port.close.assert_not_called()
        else:
            assert port.close.call_count == 1
        assert not ports._reconnect_input()
        assert not ports._reconnect_output()
        assert not ports.setup_ports()
        assert not ports._send_rtp_message(mido.Message('note_on', note=60))
        assert not ports.enqueue_rtp_message(mido.Message('note_on', note=60))
        with pytest.raises(RuntimeError, match='shutdown'):
            ports.start_background_workers()
        with pytest.raises(RuntimeError, match='shutdown'):
            ports.start_midi_monitor()
    finally:
        release.set()
        if worker is not None:
            worker.join(1)
        assert ports.close(timeout=1)
    port.close.assert_called_once()
    assert ports.playport is None
    assert ports.close(timeout=0)


def test_shutdown_budget_is_not_multiplied_by_blocked_workers():
    ports = make_ports()
    release = threading.Event()
    workers = [threading.Thread(target=lambda: release.wait(5)) for _ in range(3)]
    ports.midi_monitor_thread, ports.live_forward_thread, ports.websocket_publish_thread = workers
    for worker in workers:
        worker.start()
    try:
        started = time.monotonic()
        assert not ports.close(.02)
        assert time.monotonic() - started < .5
        ports.playport.close.assert_not_called()
    finally:
        release.set()
        for worker in workers:
            worker.join(1)
        assert ports.close(1)


def test_shutdown_requested_from_forward_worker_does_not_wait_for_itself():
    ports = make_ports()
    requested = threading.Event()
    results = []

    def forward():
        results.append(ports.close(1))
        requested.set()

    ports.live_forward_thread = threading.Thread(target=forward)
    ports.live_forward_thread.start()
    assert requested.wait(.5)
    ports.live_forward_thread.join(1)
    assert results == [False]
    assert ports.close(1)


def test_async_panic_coalesces_requests_and_shutdown_preserves_its_native_owner():
    ports = make_ports()
    port = ports.playport
    entered, release = threading.Event(), threading.Event()

    def send(_message):
        entered.set()
        assert release.wait(5)

    port.send.side_effect = send
    try:
        started = time.monotonic()
        assert ports.request_all_notes_off()
        assert time.monotonic() - started < .5
        assert entered.wait(1)
        assert ports.is_silencing_output()
        assert ports.request_all_notes_off()
        assert ports.request_all_notes_off()
        assert port.send.call_count == 1
        assert not ports.close(.02)
        assert ports.is_silencing_output()
        port.close.assert_not_called()
        assert not ports.request_all_notes_off()
    finally:
        release.set()
        assert ports.close(1)
    assert not ports.is_silencing_output()
    port.close.assert_called_once()


def test_async_panic_queries_do_not_wait_for_the_native_output_lock():
    ports = make_ports()
    try:
        with ports._output_lock:
            started = time.monotonic()
            assert ports.request_all_notes_off()
            assert ports.is_silencing_output()
            assert ports.request_all_notes_off()
            assert time.monotonic() - started < .5
            ports.playport.send.assert_not_called()
        assert ports._panic_owner.wait_done(1)
        assert not ports.is_silencing_output()
    finally:
        assert ports.close(1)


def test_completed_panic_does_not_suppress_the_next_independent_request():
    ports = make_ports()
    port = ports.playport
    try:
        assert ports.request_all_notes_off()
        assert ports._panic_owner.wait_done(1)
        assert port.send.call_count == 48
        assert ports.request_all_notes_off()
        assert ports._panic_owner.wait_done(1)
        assert port.send.call_count == 96
        assert not ports.is_silencing_output()
    finally:
        assert ports.close(1)


def test_native_panic_callback_can_request_shutdown_without_waiting_for_itself():
    ports = make_ports()
    requested = threading.Event()
    results = []
    port = ports.playport

    def send(_message):
        if not requested.is_set():
            results.append(ports.close(1))
            port.close.assert_not_called()
            requested.set()

    port.send.side_effect = send
    ports.request_all_notes_off()
    assert requested.wait(.5)
    assert results == [False]
    assert ports.close(1)
    port.close.assert_called_once()


class NativeInput:
    def __init__(self):
        self.events = deque()
        self.close_port = Mock()
        self.delete = Mock()

    def ignore_types(self, **_kwargs):
        pass

    def get_ports(self):
        return ['native']

    def open_port(self, _index):
        pass

    def get_message(self):
        try:
            return self.events.popleft()
        except IndexError:
            return None


@pytest.mark.parametrize('stage', ['get_message', 'close_port', 'delete'])
def test_buffered_input_keeps_native_owner_until_blocked_call_returns(stage):
    native = NativeInput()
    entered, release = threading.Event(), threading.Event()
    calls = []

    def block():
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(5)

    setattr(native, stage, Mock(side_effect=block))
    port = BufferedMidiInput('native', Mock(), native_input=native)
    try:
        started = time.monotonic()
        with pytest.raises(RuntimeError, match='refusing concurrent'):
            port.close(.02)
        assert time.monotonic() - started < .5
        assert entered.wait(1)
        with pytest.raises(RuntimeError, match='refusing concurrent'):
            port.close(.02)
        assert port.shutdown_status['pending']
        assert len(calls) == 1
        if stage == 'get_message':
            native.close_port.assert_not_called()
        if stage != 'delete':
            native.delete.assert_not_called()
    finally:
        release.set()
        assert port.close(1)
    native.close_port.assert_called_once()
    native.delete.assert_called_once()


def test_buffered_input_close_from_its_callback_is_deferred_until_callback_returns():
    native = NativeInput()
    callback_ready, requested = threading.Event(), threading.Event()
    results = []

    def receive(_message):
        assert callback_ready.wait(1)
        results.append(port.close(1))
        native.close_port.assert_not_called()
        requested.set()

    native.events.append(([0x90, 60, 100], 0))
    port = BufferedMidiInput('native', receive, native_input=native)
    callback_ready.set()
    assert requested.wait(.5)
    assert results == [False]
    assert port.close(1)


def test_input_event_returning_after_shutdown_is_not_admitted_to_callback():
    native = NativeInput()
    entered, release = threading.Event(), threading.Event()
    callback = Mock()

    def receive_native():
        entered.set()
        assert release.wait(5)
        return ([0x90, 60, 100], 0)

    native.get_message = Mock(side_effect=receive_native)
    port = BufferedMidiInput('native', callback, native_input=native)
    try:
        assert entered.wait(1)
        with pytest.raises(RuntimeError, match='refusing concurrent'):
            port.close(.02)
        assert port.closed  # Unavailable for reuse, even while native cleanup is pending.
        assert port.shutdown_status['pending']
    finally:
        release.set()
        assert port.close(1)
    callback.assert_not_called()


@pytest.mark.parametrize('stage', ['close_port', 'delete'])
def test_buffered_input_failed_cleanup_retries_only_unfinished_native_steps(stage):
    native = NativeInput()
    getattr(native, stage).side_effect = [OSError('disconnected'), None]
    port = BufferedMidiInput('native', Mock(), native_input=native)
    with pytest.raises(RuntimeError, match='refusing concurrent'):
        port.close(1)
    assert port.shutdown_status['error'] == 'disconnected'
    assert port.close(1)
    assert native.close_port.call_count == (2 if stage == 'close_port' else 1)
    assert native.delete.call_count == (2 if stage == 'delete' else 1)


@pytest.mark.parametrize('stage', ['close', 'panic'])
def test_learning_output_retains_owner_through_native_cleanup_stall(stage):
    entered, release = threading.Event(), threading.Event()
    port = Mock()

    def block(*_args):
        entered.set()
        assert release.wait(5)

    if stage == 'close':
        port.close.side_effect = block
    else:
        def send(message):
            if message.type == 'note_on':
                raise OSError('disconnected')
            block()
        port.send.side_effect = send
    worker = LearningOutput(port)
    if stage == 'panic':
        assert worker.enqueue(mido.Message('note_on', note=60))
    try:
        started = time.monotonic()
        assert not worker.close(.02)
        assert time.monotonic() - started < .5
        assert entered.wait(1)
        assert not worker.close(.02)
        assert not worker.finished
        assert not worker.enqueue(mido.Message('note_on', note=62))
        if stage == 'panic':
            port.close.assert_not_called()
        else:
            assert port.close.call_count == 1
    finally:
        release.set()
        result = worker.close(1)
        assert result is (stage == 'close')
    assert worker.finished
    port.close.assert_called_once()


def test_learning_output_retries_failed_close_without_replaying_notes():
    port = Mock()
    port.close.side_effect = [OSError('close failed'), None]
    worker = LearningOutput(port)
    assert worker.enqueue(mido.Message('note_on', note=60))
    assert not worker.close(1)
    assert not worker.finished
    assert worker.shutdown_status['error'] == 'close failed'
    assert not worker.close(1)  # The send/close failure stays visible to its caller.
    assert worker.finished
    assert port.send.call_count == 1
    assert port.close.call_count == 2


def test_bridge_close_is_bounded_even_while_reconcile_holds_lock_in_native_open():
    entered, release = threading.Event(), threading.Event()
    settings = Mock()
    settings.get_setting_value.side_effect = {
        'learning_piano_input': 'Piano:Keys 20:0',
        'learning_piano_output': 'Piano:Keys 20:0',
        'learning_computer_input': 'rtpmidid:Computer 30:0',
        'learning_computer_output': 'rtpmidid:Computer 30:0',
    }.get
    opened = []

    def open_output(_name):
        entered.set()
        assert release.wait(5)
        port = Mock()
        opened.append(port)
        return port

    bridge = LearningBridge(MidiQueues(), settings, open_output=open_output,
                            open_input=Mock(), verify_links=Mock())
    reconcile = threading.Thread(target=bridge.reconcile,
                                 args=(['Piano:Keys 20:0', 'rtpmidid:Computer 30:0'],) * 2)
    reconcile.start()
    try:
        assert entered.wait(1)
        started = time.monotonic()
        assert not bridge.close(.02)
        assert time.monotonic() - started < .5
        assert not bridge.reopen()
        assert not bridge.close(.02)
        assert bridge.shutdown_status['pending']
    finally:
        release.set()
        reconcile.join(1)
        assert bridge.close(1)
    assert len(opened) == 1
    opened[0].close.assert_called_once()
    assert bridge.reopen()
    assert bridge.close(1)


@pytest.mark.parametrize('kind', ['input', 'output'])
def test_reconnect_keeps_failed_old_handle_and_does_not_open_its_replacement(kind, monkeypatch):
    ports = make_ports()
    ports.usersettings = Mock()
    ports.usersettings.get_setting_value.return_value = 'new'
    ports.actual_input_port = 'old'
    ports.actual_play_port = 'old'
    ports._refresh_runtime_port_labels = Mock(return_value={'input_changed': False, 'play_changed': False})
    ports._resolve_input_target = Mock()
    ports._resolve_output_target = Mock()
    ports._resolve_selected_port = Mock(return_value='new')
    ports._should_keep_current_port = Mock(return_value=False)
    ports._configure_input_backend_filters = Mock()
    monkeypatch.setattr('lib.midiports._get_cached_input_names', lambda: ['new'])
    monkeypatch.setattr('lib.midiports._get_cached_output_names', lambda: ['new'])
    opener = Mock(return_value=Mock())
    target = 'lib.midiports.open_midi_input' if kind == 'input' else 'lib.midiports.mido.open_output'
    monkeypatch.setattr(target, opener)
    name = 'inport' if kind == 'input' else 'playport'
    old = getattr(ports, name)
    old.close.side_effect = [OSError('cleanup failed'), None]
    reconnect = ports._reconnect_input if kind == 'input' else ports._reconnect_output

    with pytest.raises(OSError, match='cleanup failed'):
        reconnect(force=True)
    assert getattr(ports, name) is old
    opener.assert_not_called()
    assert reconnect(force=True)
    assert old.close.call_count == 2
    opener.assert_called_once()
    assert getattr(ports, name) is opener.return_value
    assert ports.close(1)
