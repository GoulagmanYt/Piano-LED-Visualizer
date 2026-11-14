"""Musical behavior through the public learning player, without a MIDI device."""

import mido
import pytest
from test_learnmidi_playback import play


def melody(player, monkeypatch, batches):
    player.practice = 0
    iterator = iter(batches)
    calls = []

    def drain():
        calls.append(player.clock.now)
        if len(calls) > 10:
            player.is_started_midi = False
            pytest.fail("the player did not accept the expected chord")
        return next(iterator, [])

    monkeypatch.setattr(player.input_adapter, "drain_note_events", drain)
    return calls


def test_mixed_hand_chord_scores_the_target_hands_using_input_timestamps(player, monkeypatch):
    melody(player, monkeypatch, [[
        (mido.Message("note_on", note=60), 1.10),
        (mido.Message("note_on", note=48), 1.20),
    ]])
    monkeypatch.setattr("lib.learnmidi.time.time", lambda: 1_000_000_000)
    play(player, [mido.Message("note_on", note=60, channel=1),
                  mido.Message("note_on", note=48, channel=2),
                  mido.Message("note_off", note=48, channel=2, time=480)])
    assert [point[0] for point in player.right_hand_timing] == [0.0]
    assert [point[1] for point in player.right_hand_timing] == pytest.approx([0.10])
    assert [point[0] for point in player.left_hand_timing] == [0.0]
    assert [point[1] for point in player.left_hand_timing] == pytest.approx([0.20])


def test_positive_delta_on_meta_separates_chords(player, monkeypatch):
    calls = melody(player, monkeypatch, [
        [(mido.Message("note_on", note=60), 1.10)],
        [(mido.Message("note_on", note=64), 1.60)],
    ])
    play(player, [mido.Message("note_on", note=60, channel=1),
                  mido.MetaMessage("marker", text="next", time=480),
                  mido.Message("note_on", note=64, channel=1),
                  mido.Message("note_off", note=64, channel=1, time=480)])
    assert len(calls) == 2
    assert [point[0] for point in player.right_hand_timing] == pytest.approx([0.0, 0.5])
    assert [point[1] for point in player.right_hand_timing] == pytest.approx([0.10, 0.10])


def test_repressing_one_chord_note_does_not_farm_score(player, monkeypatch):
    melody(player, monkeypatch, [[
        (mido.Message("note_on", note=60), 1.10),
        (mido.Message("note_off", note=60), 1.11),
        (mido.Message("note_on", note=60), 1.12),
        (mido.Message("note_on", note=64), 1.13),
    ]])
    play(player, [mido.Message("note_on", note=60, channel=1),
                  mido.Message("note_on", note=64, channel=1),
                  mido.Message("note_off", note=60, channel=1, time=480)])
    assert len(player.right_hand_timing) == 2
    assert player.score_manager.get_combo() == 2


def test_hidden_wrong_note_still_penalizes_and_counts_a_mistake(player, monkeypatch):
    player.show_wrong_notes = 0
    melody(player, monkeypatch, [[
        (mido.Message("note_on", note=65), 1.10),
        (mido.Message("note_on", note=60), 1.20),
    ]])
    play(player, [mido.Message("note_on", note=60, channel=1),
                  mido.Message("note_off", note=60, channel=1, time=480)])
    assert player.mistakes_count == 1
    assert player.right_hand_mistakes == [0.0]


def test_a_final_chord_with_no_later_note_event_is_awaited(player, monkeypatch):
    calls = melody(player, monkeypatch, [[(mido.Message("note_on", note=60), 1.10)]])
    play(player, [mido.Message("note_on", note=60, channel=1)])
    assert len(calls) == 1
    assert len(player.right_hand_timing) == 1


def test_loading_many_tracks_keeps_protocol_channels_and_assigns_only_two_hands(player, song_path):
    song = mido.MidiFile()
    song.tracks.append(mido.MidiTrack([mido.MetaMessage("set_tempo", tempo=500000)]))
    for index in range(20):
        song.tracks.append(mido.MidiTrack([mido.Message("note_on", note=40 + index, channel=index % 16)]))
    song.save(song_path)
    player.load_midi(song_path.name)
    assert player.loading == 4
    notes = [(i, msg) for i, msg in enumerate(player.song_tracks) if msg.type == "note_on"]
    assert [msg.channel for _, msg in notes] == [i % 16 for i in range(20)]
    assert [player.song_hands[i] for i, _ in notes] == [1, 2] + [0] * 18


def test_one_playable_track_after_conductor_is_right_hand(player, song_path):
    song = mido.MidiFile()
    song.tracks.extend([mido.MidiTrack([mido.MetaMessage("set_tempo", tempo=500000)]),
                        mido.MidiTrack([mido.Message("note_on", note=60, channel=0)])])
    song.save(song_path)
    player.load_midi(song_path.name)
    assert player.loading == 4
    index = next(i for i, msg in enumerate(player.song_tracks) if msg.type == "note_on")
    assert player.song_hands[index] == 1
    assert player.song_tracks[index].channel == 0


def test_note_off_on_one_input_channel_does_not_release_another(player, monkeypatch):
    melody(player, monkeypatch, [[
        (mido.Message("note_on", note=60, channel=0), 1.10),
        (mido.Message("note_on", note=60, channel=1), 1.11),
        (mido.Message("note_off", note=60, channel=0), 1.12),
        (mido.Message("note_on", note=64, channel=0), 1.13),
    ]])
    play(player, [mido.Message("note_on", note=60, channel=1),
                  mido.Message("note_on", note=64, channel=1)])
    assert player.learning_state == "stopped"
    assert player.score_manager.get_combo() == 2


def test_pending_accompaniment_survives_wrong_key_and_keeps_original_channel(player, monkeypatch):
    player.hands = 1
    melody(player, monkeypatch, [[
        (mido.Message("note_on", note=65), 1.10),
        (mido.Message("note_on", note=60), 1.20),
    ]])
    # Accompaniment occurs before the target in the same MIDI tick group.
    player.song_hands = [2, 1, 2]
    play(player, [mido.Message("note_on", note=48, channel=7),
                  mido.Message("note_on", note=60, channel=4),
                  mido.Message("note_off", note=48, channel=7, time=480)])
    assert [(msg.type, msg.channel, msg.note) for msg, _ in player.sent] == [
        ("note_on", 7, 48), ("note_off", 7, 48)]
    assert player.mistakes_count == 1


def test_stop_uses_nonblocking_panic_and_start_waits_until_it_finishes(player, monkeypatch):
    from unittest.mock import Mock

    request = Mock(return_value=True)
    player.midiports.request_all_notes_off = request
    player.stop_learning()
    request.assert_called_once()
    player.midiports.send_all_notes_off.assert_not_called()
    player.midiports.is_silencing_output = lambda: True
    run = Mock()
    monkeypatch.setattr(player, "_run_learning", run)
    player.learn_midi()
    run.assert_not_called()
    assert player.stop_event.is_set()
