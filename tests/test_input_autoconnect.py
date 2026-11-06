"""Input Auto and audit regressions 15–19, without MIDI or LCD hardware."""

from types import SimpleNamespace
from unittest.mock import Mock
from xml.dom import minidom

import pytest

from lib import midiport_resolver as resolver
from lib.menulcd import MenuLCD
from lib.midiports import MidiPorts


USB = "USB Piano:USB Piano MIDI 1 24:0"
ROLAND = "Roland:Roland MIDI 1 20:0"
THROUGH = "Midi Through:Midi Through Port-0 14:0"


class FakePort:
    closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def runtime(monkeypatch):
    inputs = [USB]
    settings = {"input_port": "default", "secondary_input_port": "default", "play_port": "None"}
    usersettings = SimpleNamespace(
        get_setting_value=settings.get,
        change_setting_value=settings.__setitem__,
    )
    monkeypatch.setattr("lib.midiports._refresh_port_cache", lambda: None)
    monkeypatch.setattr("lib.midiports._get_cached_input_names", lambda: list(inputs))
    monkeypatch.setattr("lib.midiports._get_cached_output_names", lambda: [])
    monkeypatch.setattr(MidiPorts, "setup_ports", lambda self: None)
    monkeypatch.setattr(MidiPorts, "start_background_workers", lambda self: None)
    opened = []

    def open_input(name, callback):
        opened.append(name)
        return FakePort()

    monkeypatch.setattr("lib.midiports.open_midi_input", open_input)
    midi = MidiPorts(usersettings)
    midi.menu = SimpleNamespace(render_message=Mock(), show=Mock())
    return SimpleNamespace(midi=midi, inputs=inputs, settings=settings, opened=opened)


def test_auto_input_sentinel():
    for value in (None, "", "default"):
        assert resolver.is_auto_input_port(value)
    for value in (USB, "None", "off", "Auto"):
        assert not resolver.is_auto_input_port(value)


def test_default_prefers_current_safe_device():
    assert resolver.pick_default_input_port([ROLAND, USB], preferred_port=USB) == USB


def test_default_follows_preferred_device_alsa_renumbering():
    renamed = "USB Piano:USB Piano MIDI 1 32:0"
    assert resolver.pick_default_input_port([ROLAND, renamed], preferred_port=USB) == renamed


def test_default_does_not_prefer_excluded_device():
    for excluded in (THROUGH, "rpi:Virtual 16:0", "rtpmidid:Remote Piano 128:3"):
        assert resolver.pick_default_input_port([excluded, USB], preferred_port=excluded) == USB


def test_excluded_preference_cannot_match_a_similarly_named_safe_device():
    assert resolver.pick_default_input_port(
        [ROLAND, "Piano 32:0"], preferred_port="rtpmidid:Piano 128:3",
    ) == ROLAND


def test_default_falls_back_when_preferred_device_disappears():
    assert resolver.pick_default_input_port([ROLAND], preferred_port=USB) == ROLAND
    assert resolver.pick_default_input_port([], preferred_port=USB) is None


def test_auto_keeps_current_input_when_new_device_is_listed_first(runtime):
    midi = runtime.midi
    midi._reconnect_input()
    original_handle = midi.inport
    runtime.inputs.insert(0, ROLAND)
    assert not midi.ports_need_reconnect()
    assert not midi._reconnect_input()
    assert midi.inport is original_handle
    assert midi.actual_input_port == USB
    assert runtime.settings["input_port"] == "default"


def test_auto_keeps_device_identity_after_alsa_renumbering(runtime):
    midi = runtime.midi
    midi._reconnect_input()
    original_handle = midi.inport
    renamed = "USB Piano:USB Piano MIDI 1 32:0"
    runtime.inputs[:] = [ROLAND, renamed]
    assert midi.ports_need_reconnect()
    assert midi._reconnect_input()
    assert midi.actual_input_port == renamed
    assert original_handle.closed
    assert runtime.settings["input_port"] == "default"


def test_auto_falls_back_when_connected_device_is_unplugged(runtime):
    midi = runtime.midi
    midi._reconnect_input()
    original_handle = midi.inport
    runtime.inputs[:] = [ROLAND]
    midi._reconnect_input()
    assert midi.actual_input_port == ROLAND
    assert original_handle.closed
    assert runtime.settings["input_port"] == "default"


def test_auto_tracks_device_when_another_device_reuses_its_alsa_slot(runtime):
    midi = runtime.midi
    midi._reconnect_input()
    renamed = "USB Piano:USB Piano MIDI 1 32:0"
    replacement = "Roland:Roland MIDI 1 24:0"
    runtime.inputs[:] = [replacement, renamed]
    midi._reconnect_input()
    assert midi.actual_input_port == renamed
    assert runtime.settings["input_port"] == "default"


@pytest.mark.parametrize("refresh", ["diagnostics", "output"])
def test_refresh_does_not_hide_required_auto_input_reconnection(runtime, refresh):
    midi = runtime.midi
    midi._reconnect_input()
    original_handle = midi.inport
    renamed = "USB Piano:USB Piano MIDI 1 32:0"
    replacement = "Roland:Roland MIDI 1 24:0"
    runtime.inputs[:] = [replacement, renamed]
    if refresh == "diagnostics":
        midi.get_rtp_diagnostics()
    else:
        midi._reconnect_output()
    assert midi.ports_need_reconnect()
    assert midi._reconnect_input()
    assert midi.actual_input_port == renamed
    assert runtime.opened == [USB, renamed]
    assert original_handle.closed


def test_diagnostics_refresh_does_not_adopt_unrelated_device_when_piano_is_gone(runtime):
    midi = runtime.midi
    midi._reconnect_input()
    replacement = "Other Piano:Other Piano MIDI 1 24:0"
    runtime.inputs[:] = [ROLAND, replacement]
    midi.get_rtp_diagnostics()
    midi._reconnect_input()
    assert midi.actual_input_port == ROLAND


def test_auto_waits_and_connects_when_a_device_appears(runtime):
    runtime.inputs.clear()
    midi = runtime.midi
    midi._reconnect_input()
    assert midi.inport is None
    assert runtime.settings["input_port"] == "default"
    runtime.inputs.append(USB)
    midi._auto_reconnect_once(False, False, False)
    assert midi.actual_input_port == USB
    assert runtime.settings["input_port"] == "default"


def test_invalid_secondary_never_overwrites_primary_during_monitor_loop(runtime):
    runtime.settings.update(input_port=USB, secondary_input_port=THROUGH)
    runtime.inputs[:] = [ROLAND, USB, THROUGH]
    midi = runtime.midi
    midi._reconnect_input()
    for _ in range(2):
        present = midi._auto_reconnect_once(True, False, False)
        assert runtime.settings["input_port"] == USB
        assert runtime.settings["secondary_input_port"] == THROUGH
        assert midi.actual_input_port == USB
        assert not present[1]


def test_secondary_resolution_leaves_primary_diagnostics_untouched(runtime, monkeypatch):
    runtime.settings.update(input_port=USB, secondary_input_port=ROLAND)
    runtime.inputs[:] = [USB, ROLAND]
    midi = runtime.midi
    midi._reconnect_input()
    primary_reason = midi.last_resolution_reason["input"]
    # Keep the final reconnect probe from hiding the secondary's diagnostic writes.
    monkeypatch.setattr(midi, "ports_need_reconnect", lambda: False)
    midi._auto_reconnect_once(True, True, False)
    assert midi.last_resolved_input_port == USB
    assert midi.last_resolution_reason["input"] == primary_reason


def test_explicit_missing_input_waits_instead_of_using_auto(runtime):
    runtime.settings["input_port"] = ROLAND
    runtime.midi._reconnect_input()
    assert runtime.midi.actual_input_port is None
    assert runtime.settings["input_port"] == ROLAND


def test_change_port_accepts_auto_without_a_device(runtime):
    runtime.inputs.clear()
    runtime.midi.change_port("inport", "default")
    assert runtime.settings["input_port"] == "default"
    assert runtime.midi.actual_input_port is None
    assert runtime.midi.menu.render_message.call_args.args[0] == "Changing inport to:"


def test_change_port_still_reports_unavailable_explicit_input(runtime):
    runtime.midi.change_port("inport", ROLAND)
    assert runtime.settings["input_port"] == ROLAND
    assert runtime.midi.menu.render_message.call_args.args[0] == "Can't change inport to:"


def make_menu():
    menu = object.__new__(MenuLCD)
    menu.DOMTree = minidom.parseString(
        '<menu><Ports_Settings text="Input"/><Ports_Settings text="Playback"/></menu>'
    )
    return menu


def port_labels(menu, tag):
    return [node.getAttribute("text") for node in menu.DOMTree.getElementsByTagName(tag)]


def test_lcd_input_has_auto_first_without_duplicates(monkeypatch):
    menu = make_menu()
    monkeypatch.setattr("lib.menulcd.mido.get_input_names", lambda: [USB, USB])
    monkeypatch.setattr("lib.menulcd.mido.get_output_names", lambda: [])
    menu.update_ports()
    menu.update_ports()
    assert port_labels(menu, "Input") == ["Auto", USB]


def test_lcd_playback_uses_outputs_instead_of_inputs(monkeypatch):
    menu = make_menu()
    synth = "Software Synth:Synth input 40:0"
    monkeypatch.setattr("lib.menulcd.mido.get_input_names", lambda: [USB])
    monkeypatch.setattr("lib.menulcd.mido.get_output_names", lambda: [synth, synth])
    menu.update_ports()
    assert port_labels(menu, "Playback") == [synth]


def test_lcd_auto_choice_becomes_persistent_default(runtime):
    menu = make_menu()
    menu.text_color = "White"
    menu.background_color = "Black"
    menu.midiports = runtime.midi
    runtime.settings["input_port"] = ROLAND
    menu.change_settings("Auto", "Input")
    assert runtime.settings["input_port"] == "default"
    assert runtime.midi.actual_input_port == USB
