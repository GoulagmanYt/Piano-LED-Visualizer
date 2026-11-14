#!/usr/bin/env python3

import sys

import mido
import pytest

sys.path.append("./")
sys.path.append("../")

from lib import learnmidi


class StringHostileMidiMessage:
    def __init__(self, msg_type, note, velocity):
        self.type = msg_type
        self.note = note
        self.velocity = velocity

    def __str__(self):
        raise AssertionError("MIDI note parsing must not call str(msg)")


@pytest.mark.parametrize(
    ("msg_type", "velocity", "expected_velocity"),
    [
        ("note_on", 96, 96),
        ("note_on", 0, 0),
        ("note_off", 96, 0),
    ],
)
def test_extract_midi_note_velocity_reads_mido_attributes_without_string_parsing(
    msg_type,
    velocity,
    expected_velocity,
):
    msg = StringHostileMidiMessage(msg_type, note=64, velocity=velocity)

    assert learnmidi._extract_midi_note_velocity(msg) == (64, expected_velocity)



def test_learn_midi_note_drain_uses_attributes_without_string_parsing(player, monkeypatch):
    from test_learnmidi_playback import play

    player.practice = 0
    incoming = StringHostileMidiMessage("note_on", note=60, velocity=96)
    monkeypatch.setattr(player.input_adapter, "drain_note_events", lambda: [(incoming, 1.1)])
    play(player, [mido.Message("note_on", note=60, channel=1),
                  mido.Message("note_off", note=60, channel=1, time=480)])
    assert player.learning_state == "stopped"
    assert player.score_manager.get_combo() == 1
