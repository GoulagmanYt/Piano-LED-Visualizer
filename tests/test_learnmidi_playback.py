"""Exercise the legacy learning player with a deterministic clock and MIDI output."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import mido
import pytest

from lib import learnmidi
from lib.midi_queues import MidiQueues


@pytest.fixture
def player(monkeypatch):
    values = {
        "hand_colorList": "[[255, 0, 0], [0, 0, 255]]",
        "end_point": "100", "set_tempo": "100", "practice": "2",
    }
    settings = SimpleNamespace(get_setting_value=lambda key: values.get(key, "0"))
    sent = []
    ports = SimpleNamespace(
        queues=MidiQueues(),
        schedule_rtp_message=lambda msg, **kw: sent.append((msg.copy(), kw["due_time"])),
        send_all_notes_off=Mock(),
    )
    learning = learnmidi.LearnMIDI(settings, Mock(), ports, SimpleNamespace(strip=Mock()))
    learning.loading = 4
    learning.ticks_per_beat = 480
    learning.sent = sent
    learning.socket_send = []
    learning.clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(learnmidi.time, "perf_counter", lambda: learning.clock.now)
    monkeypatch.setattr(learnmidi, "fastColorWipe", lambda *args: None)
    monkeypatch.setattr(learnmidi, "get_note_position", lambda *args: 20)

    def wait(delay):
        learning.clock.now += max(0, delay)
        return learning.stop_event.is_set() or not learning.is_started_midi

    monkeypatch.setattr(learning, "_wait_or_stopped", wait)
    return learning


def play(player, messages):
    player.song_tracks = messages
    mid = mido.MidiFile(ticks_per_beat=480)
    mid.tracks.append(mido.MidiTrack(messages))
    player.notes_time = learnmidi.compute_notes_time(mid)
    player.learn_midi()


def test_tempo_changes_apply_after_their_delta(player):
    play(player, [
        mido.Message("note_on", note=60, velocity=90),
        mido.MetaMessage("set_tempo", tempo=1000000, time=480),
        mido.Message("note_off", note=60, time=480),
    ])
    assert [due for _, due in player.sent] == pytest.approx([1.0, 2.5])


def test_small_deltas_do_not_accumulate_a_three_millisecond_advance(player):
    play(player, [mido.Message("note_on", note=60, time=48) for _ in range(40)])
    assert player.sent[-1][1] == pytest.approx(3.0)


def test_section_uses_tempo_and_non_meta_index_from_before_the_start(player):
    player.start_point = 50
    play(player, [
        mido.MetaMessage("set_tempo", tempo=1000000),
        mido.Message("note_on", note=60),
        mido.MetaMessage("marker", text="section", time=480),
        mido.Message("note_off", note=60, time=480),
        mido.Message("note_on", note=62, time=480),
        mido.Message("note_off", note=62, time=480),
    ])
    assert [due for _, due in player.sent] == pytest.approx([2.0, 3.0, 4.0])
    timestamps = [item for item in player.socket_send if isinstance(item, (int, float))]
    assert timestamps == pytest.approx([2.0, 3.0, 4.0])


def test_natural_completion_releases_session_and_silences_truncated_notes(player):
    play(player, [mido.Message("note_on", note=60, velocity=90)])
    assert player.learning_state == "stopped"
    assert not player.is_started_midi
    assert player.pending_software_notes == []
    player.midiports.send_all_notes_off.assert_called_once()


def test_processing_error_also_releases_session_and_silences_output(player, monkeypatch):
    monkeypatch.setattr(learnmidi, "get_note_position", Mock(side_effect=RuntimeError("strip unavailable")))
    play(player, [mido.Message("note_on", note=60, velocity=90)])
    assert player.learning_state == "error"
    assert not player.is_started_midi
    player.midiports.send_all_notes_off.assert_called_once()


def test_stop_during_startup_does_not_leave_pending_notes(player, monkeypatch):
    player.pending_software_notes.append(mido.Message("note_on", note=70))

    def stop_on_wait(delay):
        player.is_started_midi = False
        return True

    monkeypatch.setattr(player, "_wait_or_stopped", stop_on_wait)
    play(player, [mido.Message("note_on", note=60)])
    assert not player.pending_software_notes
    player.midiports.send_all_notes_off.assert_called_once()


def test_startup_exception_releases_session(player):
    player.score_manager.reset = Mock(side_effect=RuntimeError("score unavailable"))
    play(player, [mido.Message("note_on", note=60)])
    assert player.learning_state == "error"
    assert not player.is_started_midi
    player.midiports.send_all_notes_off.assert_called_once()


def test_stopping_worker_cannot_be_revived_by_another_start(player, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def run():
        calls.append(1)
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(player, "_run_learning", run)
    worker = threading.Thread(target=player.learn_midi)
    worker.start()
    try:
        assert entered.wait(1)
        player.stop_learning()
        player.learn_midi()
        assert calls == [1]
        assert player.stop_event.is_set()
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()


def test_restart_refuses_a_worker_that_outlives_the_join_timeout(player):
    owner = Mock()
    owner.is_alive.return_value = True
    player._learning_thread = owner
    player.t = owner
    player.is_started_midi = True
    player.restart_learning()
    owner.join.assert_called_once_with(timeout=2)
    assert player.t is owner
    assert player.stop_event.is_set()


def test_completion_clears_only_learning_queue_and_panics(player):
    queues = player.midiports.queues
    queues.enqueue_scheduled_forward(mido.Message("note_on", note=70),
                                     due_time=100, source="live")

    def schedule(msg, *, due_time, source):
        queues.enqueue_scheduled_forward(msg, due_time=due_time, source=source)

    player.midiports.schedule_rtp_message = schedule
    play(player, [mido.Message("note_on", note=60)])
    assert queues.snapshot_depths()["scheduled_forward"] == 1
    assert queues.pop_due_scheduled_forward(now_perf=100)[0].note == 70
    player.midiports.send_all_notes_off.assert_called_once()


def test_note_off_release_velocity_does_not_light_a_key(player):
    play(player, [mido.Message("note_off", note=60, velocity=90, channel=1)])
    assert player.ledstrip.strip.setPixelColor.call_args.args[1] == learnmidi.Color(0, 0, 0)


def test_start_is_refused_until_external_stop_cleanup_finishes(player, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def clear(*, source):
        entered.set()
        assert release.wait(2)

    player.midiports.clear_scheduled_rtp_messages = clear
    run = Mock()
    monkeypatch.setattr(player, "_run_learning", run)
    worker = threading.Thread(target=player.stop_learning)
    worker.start()
    try:
        assert entered.wait(1)
        player.learn_midi()
        run.assert_not_called()
        assert player.stop_event.is_set()
    finally:
        release.set()
        worker.join(2)
    assert not worker.is_alive()
