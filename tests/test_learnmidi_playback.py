"""Exercise the legacy learning player with a deterministic clock and MIDI output."""

import json
import os
import pickle
import threading
from pathlib import Path
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


def save_song(path, note):
    song = mido.MidiFile(ticks_per_beat=480)
    song.tracks.append(mido.MidiTrack([
        mido.Message("note_on", note=note, velocity=90),
        mido.Message("note_off", note=note, time=480),
    ]))
    song.save(path)


@pytest.fixture
def song_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Songs").mkdir()
    path = tmp_path / "Songs" / "study.mid"
    save_song(path, 60)
    return path


def test_loader_ignores_executable_legacy_cache(player, song_path):
    marker = song_path.parent / "executed"

    class LegacyPayload:
        def __reduce__(self):
            return Path.write_text, (marker, "unsafe cache executed")

    cache_dir = song_path.parent / "cache"
    cache_dir.mkdir()
    cache = cache_dir / "study.mid.p"
    cache.write_bytes(pickle.dumps(LegacyPayload()))
    player.load_midi("study.mid")
    assert player.loading == 4
    assert not marker.exists()
    assert json.loads(cache.read_text())["version"] == 1


def test_loader_reloads_a_replaced_song_and_reuses_valid_json_cache(player, song_path, monkeypatch):
    player.load_midi("study.mid")
    save_song(song_path, 62)
    stat = song_path.stat()
    # Explicitly change the identity even on filesystems with coarse mtimes.
    os.utime(song_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    player.load_midi("study.mid")
    assert player.loading == 4
    assert next(msg.note for msg in player.song_tracks if msg.type == "note_on") == 62
    monkeypatch.setattr(learnmidi.mido, "MidiFile", Mock(side_effect=AssertionError("cache should be used")))
    player.load_midi("study.mid")
    assert player.loading == 4


@pytest.mark.parametrize("error", [PermissionError("read-only cache"), ValueError("oversized cache")])
def test_cache_write_failure_does_not_reject_a_valid_song(player, song_path, monkeypatch, error):
    monkeypatch.setattr(learnmidi, "save_learning_cache", Mock(side_effect=error))
    player.load_midi("study.mid")
    assert player.loading == 4
    assert any(msg.type == "note_on" for msg in player.song_tracks)


@pytest.mark.parametrize("name", ["../study.mid", "..\\study.mid", "/outside.mid"])
def test_loader_rejects_paths_before_parsing(player, song_path, monkeypatch, name):
    parser = Mock(side_effect=AssertionError("unsafe path parsed"))
    monkeypatch.setattr(learnmidi.mido, "MidiFile", parser)
    player.load_midi(name)
    parser.assert_not_called()
    assert player.loading == 5


def test_loading_cannot_replace_a_song_still_owned_by_a_worker(player, song_path):
    owner = Mock()
    owner.is_alive.return_value = True
    player._learning_thread = owner
    player.t = owner
    player.is_started_midi = True
    previous = [mido.Message("note_on", note=70)]
    player.song_tracks = previous
    player.load_midi("study.mid")
    assert player.loading == 5
    assert player.song_tracks is previous
    owner.join.assert_called_once_with(timeout=2)


def test_source_replaced_during_parsing_does_not_poison_cache(player, song_path, monkeypatch):
    parser = mido.MidiFile
    replacement = song_path.parent / "replacement.mid"
    save_song(replacement, 62)
    replacement_bytes = replacement.read_bytes()

    def replace_after_parse(*args, **kwargs):
        parsed = parser(*args, **kwargs)
        song_path.write_bytes(replacement_bytes)
        stat = song_path.stat()
        os.utime(song_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        return parsed

    monkeypatch.setattr(learnmidi.mido, "MidiFile", replace_after_parse)
    player.load_midi("study.mid")
    assert player.loading == 4
    assert not (song_path.parent / "cache" / "study.mid.p").exists()
