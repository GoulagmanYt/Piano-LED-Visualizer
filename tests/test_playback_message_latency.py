#!/usr/bin/env python3
"""MenuLCD.render_message() sleeps while holding the LCD lock.

The scheduler must show its LCD notices off the playback path: a notice must
not delay the song start, the cleanup after an error, or stop().
"""

import sys
import threading
import time
import unittest
from unittest.mock import patch

import mido

sys.path.append("./")
sys.path.append("../")

from lib.midi_playback_scheduler import MidiPlaybackScheduler, PlaybackState
from test_midi_playback_scheduler import (
    FakeMidiPorts,
    FakeReliableClient,
    FakeSaving,
)


class BlockingMenu:
    """Behaves like MenuLCD.render_message: blocks for the display delay."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def render_message(self, title, message, delay=500):
        self.calls.append((title, message, delay))
        self.entered.set()
        self.release.wait(timeout=10)


def _simple_midi():
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.Message("note_on", note=60, velocity=100, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=0))
    return mid


class TestPlaybackMessageLatency(unittest.TestCase):
    def test_stop_is_not_blocked_by_the_already_playing_notice(self):
        menu = BlockingMenu()
        scheduler = MidiPlaybackScheduler(FakeMidiPorts(), FakeSaving(), menu, None, None)
        scheduler.state = PlaybackState.RUNNING

        # A second "Play" request arrives while a song is already running.
        player = threading.Thread(target=scheduler.play, args=("again.mid",))
        player.start()
        self.assertTrue(menu.entered.wait(timeout=2), "notice was never displayed")

        stopped = threading.Event()
        stopper = threading.Thread(target=lambda: (scheduler.stop(), stopped.set()))
        stopper.start()
        try:
            self.assertTrue(
                stopped.wait(timeout=1.0),
                "stop() must not wait for the LCD notice (it held the scheduler lock)",
            )
        finally:
            menu.release.set()
            player.join(timeout=5)
            stopper.join(timeout=5)
        self.assertEqual(menu.calls[0][:2], ("again.mid", "Already playing"))

    def test_song_start_is_not_delayed_by_the_playing_notice(self):
        menu = BlockingMenu()
        client = FakeReliableClient()
        scheduler = MidiPlaybackScheduler(
            FakeMidiPorts(),
            FakeSaving(),
            menu,
            None,
            None,
            reliable_client_factory=lambda _settings: client,
        )
        result = []

        def run():
            with patch("lib.midi_playback_scheduler.mido.MidiFile", return_value=_simple_midi()):
                result.append(scheduler.play("song.mid"))

        worker = threading.Thread(target=run)
        worker.start()
        try:
            deadline = time.monotonic() + 2.0
            while not client.calls and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(len(client.calls), 1, "playback waited for the LCD notice")
            self.assertTrue(menu.entered.wait(timeout=2))
            self.assertEqual(menu.calls[0][:2], ("Playing: ", "song.mid"))
        finally:
            menu.release.set()
            worker.join(timeout=5)
        self.assertEqual(result, [True])
        self.assertEqual(scheduler.state, PlaybackState.STOPPED)

    def test_cleanup_after_missing_file_is_not_delayed_by_the_notice(self):
        menu = BlockingMenu()
        scheduler = MidiPlaybackScheduler(FakeMidiPorts(), FakeSaving(), menu, None, None)
        done = threading.Event()

        def run():
            with patch(
                "lib.midi_playback_scheduler.mido.MidiFile", side_effect=FileNotFoundError()
            ):
                scheduler.play("missing.mid")
            done.set()

        worker = threading.Thread(target=run)
        worker.start()
        try:
            self.assertTrue(done.wait(timeout=2.0), "play() returned only after the notice ended")
        finally:
            menu.release.set()
            worker.join(timeout=5)
        self.assertIn(("missing.mid", "File not found", 2000), menu.calls)
        self.assertEqual(scheduler.state, PlaybackState.ERROR)

    def test_a_failing_menu_never_breaks_playback(self):
        class BrokenMenu:
            def render_message(self, *args, **kwargs):
                raise RuntimeError("LCD unplugged")

        client = FakeReliableClient()
        scheduler = MidiPlaybackScheduler(
            FakeMidiPorts(),
            FakeSaving(),
            BrokenMenu(),
            None,
            None,
            reliable_client_factory=lambda _settings: client,
        )
        with patch("lib.midi_playback_scheduler.mido.MidiFile", return_value=_simple_midi()):
            self.assertTrue(scheduler.play("song.mid"))
        self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
