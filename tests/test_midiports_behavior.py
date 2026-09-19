#!/usr/bin/env python3

import unittest
from unittest.mock import patch

from lib.midiports import MidiPorts


class DummySettings:
    def __init__(self, initial):
        self.values = dict(initial)

    def get_setting_value(self, name):
        return self.values.get(name)

    def change_setting_value(self, name, value):
        self.values[name] = value


class DummyPort:
    def close(self):
        pass

    def send(self, _msg):
        pass


class TestMidiPortsBehavior(unittest.TestCase):
    def test_missing_explicit_input_does_not_overwrite_requested_setting(self):
        settings = DummySettings({
            "input_port": "My Piano:Port 20:0",
            "play_port": "default",
        })

        with patch("lib.midiports._get_cached_input_names", return_value=[
            "USB AudioDevice:USB AudioDevice MIDI 1 16:0",
            "rtpmidid:OSCMidiRobin 128:3",
        ]), patch("lib.midiports._get_cached_output_names", return_value=[]), patch(
            "lib.midiports.mido.open_input", return_value=DummyPort()
        ) as open_input, patch("lib.midiports.mido.open_output", return_value=DummyPort()):
            midiports = MidiPorts(settings)

        self.assertEqual(settings.get_setting_value("input_port"), "My Piano:Port 20:0")
        self.assertIsNone(midiports.actual_input_port)
        open_input.assert_not_called()

    def test_blocked_requested_input_self_heals_to_real_device(self):
        settings = DummySettings({
            "input_port": "rtpmidid:Network Export 128:0",
            "play_port": "default",
        })

        with patch("lib.midiports._get_cached_input_names", return_value=[
            "rtpmidid:Network Export 128:0",
            "USB AudioDevice:USB AudioDevice MIDI 1 16:0",
        ]), patch("lib.midiports._get_cached_output_names", return_value=[]), patch(
            "lib.midiports.mido.open_input", return_value=DummyPort()
        ), patch("lib.midiports.mido.open_output", return_value=DummyPort()):
            midiports = MidiPorts(settings)

        self.assertEqual(
            settings.get_setting_value("input_port"),
            "USB AudioDevice:USB AudioDevice MIDI 1 16:0",
        )
        self.assertEqual(
            midiports.actual_input_port,
            "USB AudioDevice:USB AudioDevice MIDI 1 16:0",
        )

    def test_missing_rtp_output_refreshes_cache_and_connects(self):
        settings = DummySettings({
            "input_port": "default",
            "secondary_input_port": "default",
            "play_port": "rtpmidid:OSCMidiRobin 128:1",
        })

        with patch.object(MidiPorts, "setup_ports", return_value=None), patch(
            "lib.midiports._get_cached_output_names",
            side_effect=[
                [],
                [
                    "rtpmidid:Network Export 128:0",
                    "rtpmidid:Announcements 128:2",
                    "rtpmidid:OSCMidiRobin 128:3",
                ],
            ],
        ), patch("lib.midiports._refresh_port_cache"), patch(
            "lib.midiports.mido.open_output",
            return_value=DummyPort(),
        ) as open_output:
            midiports = MidiPorts(settings)
            connected = midiports._connect_port("output")

        self.assertTrue(connected)
        self.assertEqual(midiports.actual_play_port, "rtpmidid:OSCMidiRobin 128:3")
        open_output.assert_called_once_with("rtpmidid:OSCMidiRobin 128:3")

    def test_auto_reconnect_loop_reconnects_restored_rtp_session(self):
        settings = DummySettings({
            "input_port": "default",
            "secondary_input_port": "default",
            "play_port": "rtpmidid:OSCMidiRobin 128:1",
        })

        with patch.object(MidiPorts, "setup_ports", return_value=None):
            midiports = MidiPorts(settings)

        midiports.monitor_running = True
        sleep_calls = {"count": 0}

        def stop_after_second_sleep(_seconds):
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 2:
                midiports.monitor_running = False

        with patch("lib.midiports._refresh_port_cache"), patch(
            "lib.midiports._get_cached_input_names",
            return_value=[],
        ), patch(
            "lib.midiports._get_cached_output_names",
            side_effect=[
                [
                    "rtpmidid:Network Export 128:0",
                    "rtpmidid:Announcements 128:2",
                ],
                [
                    "rtpmidid:Network Export 128:0",
                    "rtpmidid:Announcements 128:2",
                    "rtpmidid:OSCMidiRobin! 128:4",
                ],
            ],
        ), patch.object(midiports, "reconnect_ports") as reconnect_ports, patch(
            "lib.midiports.time.sleep",
            side_effect=stop_after_second_sleep,
        ):
            midiports.auto_reconnect_loop()

        reconnect_ports.assert_called_once()

    def test_auto_reconnect_loop_reconnects_when_rtp_port_id_changes(self):
        settings = DummySettings({
            "input_port": "default",
            "secondary_input_port": "default",
            "play_port": "rtpmidid:OSCMidiRobin 129:1",
        })

        with patch.object(MidiPorts, "setup_ports", return_value=None):
            midiports = MidiPorts(settings)

        midiports.actual_play_port = "rtpmidid:OSCMidiRobin 129:1"
        midiports.monitor_running = True
        sleep_calls = {"count": 0}

        def stop_after_second_sleep(_seconds):
            sleep_calls["count"] += 1
            if sleep_calls["count"] >= 2:
                midiports.monitor_running = False

        with patch("lib.midiports._refresh_port_cache"), patch(
            "lib.midiports._get_cached_input_names",
            return_value=[],
        ), patch(
            "lib.midiports._get_cached_output_names",
            side_effect=[
                ["rtpmidid:OSCMidiRobin 129:1"],
                ["rtpmidid:OSCMidiRobin 128:1"],
            ],
        ), patch.object(midiports, "reconnect_ports") as reconnect_ports, patch(
            "lib.midiports.time.sleep",
            side_effect=stop_after_second_sleep,
        ):
            midiports.auto_reconnect_loop()

        reconnect_ports.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
