#!/usr/bin/env python3

import sys
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

import mido

sys.path.append("./")
sys.path.append("../")

from lib.reliable_midi_playback_client import (
    ReliablePlaybackError,
    _create_connection,
    compile_midi_file,
    compile_midi_messages,
)


class FakeSocket:
    def __init__(self):
        self.timeout = None
        self.connected_to = None
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, address):
        self.connected_to = address

    def close(self):
        self.closed = True


class TestReliableMidiPlaybackClient(unittest.TestCase):
    def test_connection_uses_resolved_numeric_endpoint(self):
        fake_socket = FakeSocket()
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.26", 5056))]

        with patch("lib.reliable_midi_playback_client.socket.getaddrinfo", return_value=addresses), patch(
            "lib.reliable_midi_playback_client.socket.socket", return_value=fake_socket
        ):
            connected = _create_connection("oscmidi-rtp.local", 5056, timeout=1.0)

        self.assertIs(connected, fake_socket)
        self.assertEqual(fake_socket.connected_to, ("192.168.1.26", 5056))
        self.assertGreater(fake_socket.timeout, 0)

    def test_connection_reports_resolution_failure(self):
        failure = socket.gaierror(-2, "Name or service not known")
        with patch("lib.reliable_midi_playback_client.socket.getaddrinfo", side_effect=failure):
            with self.assertRaisesRegex(ReliablePlaybackError, "Name or service not known"):
                _create_connection("missing.local", 5056, timeout=1.0)

    def test_compile_preserves_exact_duplicate_simultaneous_events(self):
        mid = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.Message("note_on", note=60, velocity=100, time=0))
        track.append(mido.Message("note_on", note=60, velocity=100, time=0))
        track.append(mido.Message("control_change", control=64, value=127, time=240))
        track.append(mido.Message("note_off", note=60, velocity=0, time=0))

        compiled = compile_midi_messages(mid)

        self.assertEqual(compiled.total, 4)
        self.assertEqual([event["seq"] for event in compiled.events], [0, 1, 2, 3])
        self.assertEqual([event["data"] for event in compiled.events[:2]], [[0x90, 60, 100], [0x90, 60, 100]])
        self.assertEqual(compiled.events[0]["dueUs"], compiled.events[1]["dueUs"])
        self.assertEqual(compiled.events[2]["data"], [0xB0, 64, 127])
        self.assertEqual(compiled.events[3]["data"], [0x80, 60, 0])

    def test_compile_la_campanella_counts_all_non_meta_messages(self):
        compiled = compile_midi_file(Path("Songs") / "La Campanella.mid")
        note_on_count = sum(
            1
            for event in compiled.events
            if len(event["data"]) >= 3 and event["data"][0] & 0xF0 == 0x90 and event["data"][2] > 0
        )

        self.assertEqual(compiled.total, 8556)
        self.assertEqual(note_on_count, 4266)
        self.assertEqual(compiled.events[-1]["seq"], 8555)


if __name__ == "__main__":
    unittest.main()
