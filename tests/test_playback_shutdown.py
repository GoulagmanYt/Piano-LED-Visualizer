import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

from lib.midi_playback_scheduler import MidiPlaybackScheduler
from lib.midi_queues import MidiQueues
from lib.midiports import MidiPorts


def make_ports():
    ports = MidiPorts.__new__(MidiPorts)
    ports.queues = MidiQueues()
    ports.midifile_queue = ports.queues.file_queue
    ports.monitor_stop = threading.Event()
    ports.midi_monitor_thread = None
    ports.live_forward_thread = None
    ports.websocket_publish_thread = None
    ports._output_lock = threading.RLock()
    ports._notify_forward_worker = Mock()
    ports._wake_websocket_publish_worker = Mock()
    ports.inport = None
    ports.playport = Mock()
    return ports


def make_scheduler(ports):
    return MidiPlaybackScheduler(ports, SimpleNamespace(is_playing_midi={}), None, None, None)


def test_stop_defers_native_panic_and_refuses_replay_until_panic_owner_finishes(monkeypatch):
    ports = make_ports()
    scheduler = make_scheduler(ports)
    entered, release = threading.Event(), threading.Event()

    def send(_message):
        entered.set()
        assert release.wait(5)

    ports.playport.send.side_effect = send
    midi_file = Mock()
    monkeypatch.setattr('lib.midi_playback_scheduler.mido.MidiFile', midi_file)
    monkeypatch.setattr('lib.midi_playback_scheduler.compile_midi_messages', Mock())
    scheduler._play_reliable = Mock(return_value=True)
    try:
        started = time.monotonic()
        scheduler.stop()
        assert time.monotonic() - started < .5
        assert entered.wait(1)
        assert ports.is_silencing_output()
        assert not scheduler.play('next.mid')
        midi_file.assert_not_called()
        release.set()
        assert ports._panic_owner.wait_done(1)
        assert scheduler.play('next.mid')
        midi_file.assert_called_once()
    finally:
        release.set()
        assert ports.close(1)


def test_replay_is_refused_during_stop_before_its_panic_is_admitted(monkeypatch):
    ports = make_ports()
    scheduler = make_scheduler(ports)
    playing, stop_entered = threading.Event(), threading.Event()
    finish_play, release_stop = threading.Event(), threading.Event()
    handle = SimpleNamespace(stop=lambda: (stop_entered.set(), release_stop.wait(5)))

    def play_reliable(_song, _compiled):
        scheduler._reliable_handle = handle
        playing.set()
        assert finish_play.wait(5)
        return False

    scheduler._play_reliable = play_reliable
    midi_file = Mock()
    monkeypatch.setattr('lib.midi_playback_scheduler.mido.MidiFile', midi_file)
    monkeypatch.setattr('lib.midi_playback_scheduler.compile_midi_messages', Mock())
    player = threading.Thread(target=scheduler.play, args=('old.mid',))
    stopper = threading.Thread(target=scheduler.stop)
    player.start()
    try:
        assert playing.wait(1)
        stopper.start()
        assert stop_entered.wait(1)
        finish_play.set()
        player.join(1)
        assert not player.is_alive()
        assert not ports.is_silencing_output()  # Stop has not requested it yet.
        assert not scheduler.play('next.mid')
        assert midi_file.call_count == 1
        release_stop.set()
        stopper.join(1)
        assert not stopper.is_alive()
        assert ports._panic_owner.wait_done(1)
        scheduler._play_reliable = Mock(return_value=True)
        assert scheduler.play('next.mid')
        assert midi_file.call_count == 2
    finally:
        finish_play.set()
        release_stop.set()
        player.join(1)
        if stopper.ident is not None:
            stopper.join(1)
        assert ports.close(1)
