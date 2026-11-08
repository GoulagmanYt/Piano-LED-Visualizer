#!/usr/bin/env python3
"""Tests de régression pour les bugs trouvés lors de l'audit de novembre 2026."""

import datetime
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import mido

sys.path.append("./")
sys.path.append("../")

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestProfileManagerLearningSettings(unittest.TestCase):
    def test_get_learning_settings_returns_saved_values(self):
        from lib.profile_manager import ProfileManager

        with tempfile.TemporaryDirectory() as tmp:
            songs = os.path.join(tmp, "Songs")
            os.makedirs(songs)
            Path(songs, "song.mid").write_bytes(b"x")
            manager = ProfileManager(os.path.join(tmp, "p.db"), songs_dir=songs)
            profile_id = manager.get_or_create_profile("robin")
            manager.update_learning_setting(profile_id, "song.mid", "tempo", 80)

            settings = manager.get_learning_settings(profile_id, "song.mid")

            self.assertEqual(settings["tempo"], 80)


class TestSaveMidiWithoutRecording(unittest.TestCase):
    def test_save_without_recording_does_not_raise(self):
        from lib.savemidi import SaveMIDI

        saver = SaveMIDI()
        saver.add_instance(SimpleNamespace(render_message=lambda *a, **k: None))
        saver.save("never-recorded")  # ne doit pas lever AttributeError


class TestScheduleAcrossMidnight(unittest.TestCase):
    SCHEDULE = [{"enabled": True, "days": [0], "startTime": "22:00", "endTime": "02:00"}]  # lundi 22:00 -> mardi 02:00

    def _at(self, year, month, day, hour, minute):
        import lib.functions as functions

        class FakeDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(year, month, day, hour, minute)

        fake_module = SimpleNamespace(datetime=FakeDateTime, time=datetime.time)
        with patch.object(functions, "datetime", fake_module):
            return functions.is_within_schedule(self.SCHEDULE)

    def test_evening_part_belongs_to_start_day(self):
        self.assertTrue(self._at(2026, 10, 26, 23, 0))  # lundi 23:00

    def test_after_midnight_part_belongs_to_previous_day(self):
        self.assertTrue(self._at(2026, 10, 27, 1, 0))  # mardi 01:00

    def test_early_morning_of_start_day_is_outside(self):
        self.assertFalse(self._at(2026, 10, 26, 1, 0))  # lundi 01:00 (plage du dimanche soir)

    def test_after_end_time_is_outside(self):
        self.assertFalse(self._at(2026, 10, 27, 3, 0))

    def test_same_day_range_unchanged(self):
        import lib.functions as functions

        schedule = [{"enabled": True, "days": [0], "startTime": "08:00", "endTime": "18:00"}]

        class FakeDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 26, 12, 0)

        with patch.object(functions, "datetime", SimpleNamespace(datetime=FakeDateTime, time=datetime.time)):
            self.assertTrue(functions.is_within_schedule(schedule))


class TestStateManagerReloadsConfig(unittest.TestCase):
    def test_idle_timeout_change_is_applied_without_restart(self):
        from lib.state_manager import StateManager

        class Settings:
            def __init__(self):
                self.values = {"idle_timeout_minutes": "10"}
                self.last_save = 1

            def get_setting_value(self, name):
                return self.values.get(name)

        settings = Settings()
        manager = StateManager(settings)
        self.assertEqual(manager.idle_timeout_seconds, 600)

        settings.values["idle_timeout_minutes"] = "2"
        settings.last_save = 2
        manager.update_state()

        self.assertEqual(manager.idle_timeout_seconds, 120)


class TestNotesTime(unittest.TestCase):
    def test_meta_message_deltas_are_accumulated(self):
        from lib.learnmidi import compute_notes_time

        mid = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        mid.tracks.append(track)
        track.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
        track.append(mido.Message("note_on", note=60, velocity=80, time=0))
        track.append(mido.Message("note_off", note=60, velocity=0, time=480))
        track.append(mido.MetaMessage("marker", text="B", time=480))
        track.append(mido.Message("note_on", note=62, velocity=80, time=480))
        track.append(mido.Message("note_off", note=62, velocity=0, time=480))

        times = compute_notes_time(mid)

        self.assertEqual([round(t, 3) for t in times], [0, 0.5, 1.5, 2.0])


class TestRenameMovesSheetMusic(unittest.TestCase):
    def test_non_bundle_rename_moves_sidecar_and_cache(self):
        import webinterface.views_api as views_api
        from webinterface import webinterface, app_state

        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                os.makedirs("Songs/cache")
                Path("Songs/old.mid").write_bytes(b"MThd")
                Path("Songs/old.musicxml").write_text("<x/>")
                Path("Songs/cache/old.mid.p").write_bytes(b"x")
                songs_dir = Path("Songs").resolve()
                menu = SimpleNamespace(last_activity=0, is_idle_animation_running=False)
                with patch.object(views_api, "SONGS_DIR", songs_dir), \
                        patch.object(app_state, "menu", menu, create=True), \
                        patch.object(app_state, "state_manager", None, create=True):
                    client = webinterface.test_client()
                    response = client.get(
                        "/api/change_setting",
                        query_string={"setting_name": "change_song_name", "value": "old.mid", "second_value": "new.mid"},
                    )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.get_json()["success"])
                self.assertEqual(sorted(os.listdir("Songs")), ["cache", "new.mid", "new.musicxml"])
                self.assertEqual(os.listdir("Songs/cache"), ["new.mid.p"])
            finally:
                os.chdir(previous_cwd)


class TestStartEndPointWithoutSong(unittest.TestCase):
    def test_set_current_time_points_without_song_do_not_crash(self):
        from webinterface import webinterface, app_state

        learning = SimpleNamespace(song_tracks=[], current_idx=0, start_point=0, end_point=100)
        menu = SimpleNamespace(last_activity=0, is_idle_animation_running=False)
        with patch.object(app_state, "learning", learning, create=True), \
                patch.object(app_state, "menu", menu, create=True), \
                patch.object(app_state, "state_manager", None, create=True):
            client = webinterface.test_client()
            for name in ("set_current_time_as_start_point", "set_current_time_as_end_point"):
                response = client.get("/api/change_setting", query_string={"setting_name": name, "value": ""})
                self.assertEqual(response.status_code, 200, name)
                self.assertFalse(response.get_json()["success"], name)


class TestHostnameSuffix(unittest.TestCase):
    def test_only_exact_local_suffix_is_removed(self):
        from lib.platform import _strip_local_suffix

        self.assertEqual(_strip_local_suffix("piano"), "piano")
        self.assertEqual(_strip_local_suffix("piano.local"), "piano")
        self.assertEqual(_strip_local_suffix("Radio.LOCAL"), "Radio")
        self.assertEqual(_strip_local_suffix("local"), "local")


class TestHotspotPasswordNotLogged(unittest.TestCase):
    def test_new_password_is_not_written_to_logs(self):
        import lib.platform as platform_module

        secret = "S3cretHotspotPass"
        with patch.object(platform_module.subprocess, "run", return_value=SimpleNamespace(returncode=0)), \
                patch.object(platform_module.time, "sleep"), \
                self.assertLogs(platform_module.logger, level="DEBUG") as captured:
            platform_module.PlatformRasp.change_hotspot_password(secret)

        self.assertNotIn(secret, "\n".join(captured.output))


class TestSpeedColorZeroMaxNotes(unittest.TestCase):
    def test_zero_max_notes_does_not_divide_by_zero(self):
        from lib.color_mode import ColorMode

        ledsettings = SimpleNamespace(
            speed_slowest={"red": 0, "green": 255, "blue": 0},
            speed_fastest={"red": 255, "green": 0, "blue": 0},
            speed_period_in_seconds=3.0,
            speed_max_notes=0,
        )
        color_mode = ColorMode("Speed", ledsettings)
        color_mode.NoteOn(None, 0, None, 10)  # ne doit pas lever ZeroDivisionError


class TestLcdColorSettingsArePersisted(unittest.TestCase):
    def test_every_lcd_color_menu_maps_to_existing_settings(self):
        import xml.etree.ElementTree as ET
        from lib.menulcd import LED_COLOR_SETTING_PREFIXES

        defaults = {element.tag for element in ET.parse(PROJECT_ROOT / "config" / "default_settings.xml").getroot()}
        for location, prefix in LED_COLOR_SETTING_PREFIXES.items():
            for channel in ("red", "green", "blue"):
                self.assertIn(f"{prefix}_{channel}", defaults, f"{location} -> {prefix}_{channel}")

    def test_change_value_saves_under_the_real_setting_name(self):
        from lib.menulcd import MenuLCD

        saved = {}
        ledsettings = SimpleNamespace(
            speed_slowest={"red": 10, "green": 0, "blue": 0}, speed_fastest={"red": 10, "green": 0, "blue": 0},
            gradient_start={"red": 10, "green": 0, "blue": 0}, gradient_end={"red": 10, "green": 0, "blue": 0},
            key_in_scale={"red": 10, "green": 0, "blue": 0}, key_not_in_scale={"red": 10, "green": 0, "blue": 0},
        )
        fake_menu = MagicMock()  # show(), learning, etc. sont simulés ; seuls les attributs utiles sont fixés
        fake_menu.current_location = "Color_in_scale"
        fake_menu.current_choice = "Red"
        fake_menu.speed_multiplier = 1
        fake_menu.ledsettings = ledsettings
        fake_menu.usersettings = SimpleNamespace(change_setting_value=lambda name, value: saved.__setitem__(name, value))

        MenuLCD.change_value(fake_menu, 1)

        self.assertEqual(saved, {"key_in_scale_red": 11})


class TestNoDirectHardwareImports(unittest.TestCase):
    def test_lib_modules_use_driver_shim(self):
        allowed = {"rpi_drivers.py", "null_drivers.py"}
        offenders = []
        for path in (PROJECT_ROOT / "lib").glob("*.py"):
            if path.name in allowed:
                continue
            if re.search(r"^\s*(from|import)\s+rpi_ws281x\b", path.read_text(encoding="utf-8"), re.MULTILINE):
                offenders.append(path.name)
        self.assertEqual(offenders, [])


class TestAutoinstallRetry(unittest.TestCase):
    def test_failed_command_is_retried_under_set_e(self):
        script = (PROJECT_ROOT / "autoinstall.sh").read_text(encoding="utf-8")
        match = re.search(r"^execute_command\(\) \{.*?^\}", script, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(match)
        harness = "\n".join([
            "set -euo pipefail",
            "ping() { return 0; }",
            "sleep() { :; }",
            match.group(0),
            'execute_command "false" "check_internet"',
        ])
        import shutil
        bash = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
        result = subprocess.run([bash, "-c", harness], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.count("Command failed with exit code 1."), 18)


class TestSymmetricEndpointResolution(unittest.TestCase):
    def test_symmetric_pairing_when_outputs_unset(self):
        from lib.learning_bridge import resolve_bridge_endpoints
        settings = {
            "learning_piano_input": "Digital Piano 20:0",
            "learning_piano_output": "",
            "learning_computer_input": "rtpmidid:OSCMidi 128:1",
            "learning_computer_output": "none",
        }
        inputs = ["Digital Piano 20:0", "rtpmidid:OSCMidi 128:1"]
        outputs = ["Digital Piano 20:0", "rtpmidid:OSCMidi 128:1"]
        pi, po, ci, co = resolve_bridge_endpoints(settings, inputs, outputs)
        self.assertEqual(pi, "Digital Piano 20:0")
        self.assertEqual(po, "Digital Piano 20:0")
        self.assertEqual(ci, "rtpmidid:OSCMidi 128:1")
        self.assertEqual(co, "rtpmidid:OSCMidi 128:1")

    def test_auto_fallback_to_standard_ports(self):
        from lib.learning_bridge import resolve_bridge_endpoints
        settings = {
            "learning_piano_input": "auto",
            "learning_piano_output": "auto",
            "learning_computer_input": "auto",
            "learning_computer_output": "auto",
            "input_port": "MyPiano 16:0",
            "secondary_input_port": "MyComputer 24:0",
        }
        inputs = ["MyPiano 16:0", "MyComputer 24:0"]
        outputs = ["MyPiano 16:0", "MyComputer 24:0"]
        pi, po, ci, co = resolve_bridge_endpoints(settings, inputs, outputs)
        self.assertEqual(pi, "MyPiano 16:0")
        self.assertEqual(po, "MyPiano 16:0")
        self.assertEqual(ci, "MyComputer 24:0")
        self.assertEqual(co, "MyComputer 24:0")


class TestDynamicLearningBridgeModeSwitching(unittest.TestCase):
    def test_set_learning_bridge_mode_toggles_cleanly(self):
        from lib.midiports import MidiPorts
        from lib.midi_queues import MidiQueues

        settings_dict = {"midi_bridge_mode": "normal", "input_port": "None", "secondary_input_port": "None", "play_port": "None"}
        class DummySettings:
            def get_setting_value(self, k):
                return settings_dict.get(k, "")
            def change_setting_value(self, k, v):
                settings_dict[k] = str(v)

        ports = MidiPorts.__new__(MidiPorts)
        ports.usersettings = DummySettings()
        ports.queues = MidiQueues()
        ports.learning_bridge = None
        ports.learning_bridge_enabled = False
        ports.inport = None
        ports.playport = None
        ports.actual_input_port = None
        ports.actual_play_port = None
        ports.setup_ports = MagicMock()
        ports._close_standard_ports_for_bridge = MagicMock()

        ports.set_learning_bridge_mode(True)
        self.assertTrue(ports.learning_bridge_enabled)
        self.assertEqual(settings_dict["midi_bridge_mode"], "learning")
        self.assertIsNotNone(ports.learning_bridge)
        ports.setup_ports.assert_called()

        ports.set_learning_bridge_mode(False)
        self.assertFalse(ports.learning_bridge_enabled)
        self.assertEqual(settings_dict["midi_bridge_mode"], "normal")


class TestMenuLCDModeSwitching(unittest.TestCase):
    def test_lcd_mode_toggle_and_block_control(self):
        from lib.menulcd import MenuLCD

        fake_menu = MenuLCD.__new__(MenuLCD)
        fake_midiports = SimpleNamespace(learning_bridge_enabled=False, set_learning_bridge_mode=MagicMock())
        saved = {}
        fake_menu.midiports = fake_midiports
        fake_menu.usersettings = SimpleNamespace(change_setting_value=lambda k, v: saved.__setitem__(k, v))

        fake_menu.toggle_learning_bridge_mode()
        fake_midiports.set_learning_bridge_mode.assert_called_with(True)

        fake_menu.set_learning_block_control(True)
        self.assertEqual(saved.get("learning_block_control"), "1")


class TestSurgicalDirectLinkDisconnect(unittest.TestCase):
    def test_disconnect_direct_links_removes_piano_to_computer_link(self):
        from lib.learning_bridge import disconnect_direct_links

        mock_aconnect_l = (
            "client 14: 'Midi Through' [type=kernel]\n"
            "    0 'Midi Through Port-0'\n"
            "client 16: 'USB AudioDevice' [type=kernel,card=1]\n"
            "    0 'USB AudioDevice MIDI 1'\n"
            "        Connecting To: 128:2\n"
            "client 128: 'rtpmidid' [type=user,pid=351]\n"
            "    2 'OSCMidi'\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                SimpleNamespace(stdout=mock_aconnect_l, returncode=0),
                SimpleNamespace(stdout="", returncode=0),
            ]
            res = disconnect_direct_links("Piano 16:0", "Piano 16:0", "Computer 128:2", "Computer 128:2")
            self.assertEqual(res, [("16:0", "128:2")])
            mock_run.assert_any_call(
                ["aconnect", "-d", "16:0", "128:2"],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )




class TestPulseModeActiveWhenKeylistEmpty(unittest.TestCase):
    def test_pulse_effects_process_even_when_keylist_empty(self):
        from lib.led_effects_processor import LEDEffectsProcessor
        from lib.ledstrip import ActiveIndexList

        fake_strip = SimpleNamespace(
            led_number=88,
            keylist=ActiveIndexList([0] * 88),
            keylist_status=ActiveIndexList([0] * 88),
            keylist_sustained=ActiveIndexList([0] * 88),
            keylist_color=[(0, 0, 0)] * 88,
            active_pulses=[{"pos": 10.0, "color": (255, 0, 0), "speed": 1.0, "life": 1.0}],
            strip=SimpleNamespace(setPixelColor=MagicMock()),
            set_adjacent_colors=MagicMock(),
            sustain_value=0,
        )
        fake_settings = SimpleNamespace(
            mode="Pulse",
            fadingspeed="100",
            backlight_brightness_percent="0",
            get_backlight_color=lambda c: 0,
        )
        fake_menu = SimpleNamespace(screensaver_is_running=False)
        fake_color_mode = SimpleNamespace(ColorUpdate=MagicMock())
        processor = LEDEffectsProcessor(fake_strip, fake_settings, fake_menu, fake_color_mode, 0, 10)
        processor.process_pulse_effects = MagicMock(return_value=True)

        res = processor.process_fade_effects(0.01)
        self.assertTrue(res)
        processor.process_pulse_effects.assert_called_once()


class TestSustainReleaseRecordsWhenNoNotesSustained(unittest.TestCase):
    def test_cc64_release_calls_saving_when_no_notes_sustained(self):
        import time
        from lib.midi_event_processor import MIDIEventProcessor
        from lib.ledstrip import ActiveIndexList

        fake_saving = SimpleNamespace(
            add_control_change=MagicMock(),
            is_recording=True,
            start_time=0.0,
        )
        fake_ledstrip = SimpleNamespace(
            led_number=88,
            keylist=ActiveIndexList([0] * 88),
            keylist_status=ActiveIndexList([0] * 88),
            keylist_sustained=ActiveIndexList([0] * 88),
            keylist_color=[(0, 0, 0)] * 88,
            strip=SimpleNamespace(setPixelColor=MagicMock()),
            set_adjacent_colors=MagicMock(),
        )
        fake_settings = SimpleNamespace(mode="Velocity", sequence_active=False, next_step=None)
        fake_usersettings = SimpleNamespace(get_setting_value=lambda k: "0")
        fake_ports = SimpleNamespace(last_activity=0)

        processor = MIDIEventProcessor(
            fake_ports, fake_ledstrip, fake_settings, fake_usersettings, fake_saving,
            None, None, None
        )
        msg = mido.Message("control_change", control=64, value=0)
        processor.handle_control_change(msg, time.time())
        fake_saving.add_control_change.assert_called_once_with("control_change", 0, 64, 0, unittest.mock.ANY)


class TestStateManagerScreensaverDelayRobustness(unittest.TestCase):
    def test_string_and_invalid_delays_handled(self):
        from lib.state_manager import StateManager

        fake_usersettings = SimpleNamespace(get_setting_value=lambda k: "0")
        sm = StateManager(fake_usersettings)
        menu_decimal = SimpleNamespace(screensaver_delay="5.5", screensaver_is_running=False)
        menu_invalid = SimpleNamespace(screensaver_delay="invalid", screensaver_is_running=False)
        menu_none = SimpleNamespace(screensaver_delay=None, screensaver_is_running=False)

        self.assertFalse(sm.should_run_screensaver(menu_invalid))
        self.assertFalse(sm.should_run_screensaver(menu_none))
        sm.last_user_activity = 0
        sm.last_midi_activity = 0
        self.assertTrue(sm.should_run_screensaver(menu_decimal))


class TestBufferedMidiInputCorruptedFrames(unittest.TestCase):
    def test_corrupted_frame_does_not_crash_thread(self):
        import time
        from collections import deque
        from lib.buffered_midi_input import BufferedMidiInput

        class MockNative:
            def __init__(self):
                self.events = deque([([], 0.0), ([0x90, 60, 80], 0.001)])
                self.opened = None
                self.closed = False
                self.cleaned = False
                self.filters = None

            def get_ports(self):
                return ["MockPort"]

            def open_port(self, index):
                self.opened = index

            def ignore_types(self, **kwargs):
                self.filters = kwargs

            def set_callback(self, *args):
                pass

            def get_message(self):
                try:
                    return self.events.popleft()
                except IndexError:
                    return None

            def close_port(self):
                self.closed = True

            def delete(self):
                self.cleaned = True

        native = MockNative()
        received = []
        port = BufferedMidiInput("MockPort", callback=received.append, native_input=native)
        try:
            time.sleep(0.05)
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].note, 60)
            self.assertIsNone(port.error)
        finally:
            port.close()


if __name__ == "__main__":
    unittest.main()
