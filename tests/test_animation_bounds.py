import threading
from collections import deque
from types import SimpleNamespace

import pytest

from lib import functions


class Strip:
    def __init__(self, count):
        self.pixels = [0] * count
        self.writes = []

    def numPixels(self):
        return len(self.pixels)

    def setPixelColor(self, index, color):
        assert 0 <= index < len(self.pixels), f"out-of-range LED {index}"
        self.pixels[index] = color
        self.writes.append((index, color))

    def show(self):
        pass


def make_ledstrip(count):
    return SimpleNamespace(strip=Strip(count), led_number=count,
                           keylist=[0] * count, keylist_status=[0] * count)


@pytest.mark.parametrize("adjacent_mode", ["Off", "RGB"])
@pytest.mark.parametrize("index", [-1, 5])
def test_overwrite_rejects_pixels_outside_strip(adjacent_mode, index):
    assert not functions.check_if_led_can_be_overwrite(
        index, make_ledstrip(5), SimpleNamespace(adjacent_mode=adjacent_mode))


@pytest.mark.parametrize("index", [0, 1, 4])
def test_adjacent_animation_preserves_active_notes_at_strip_edges(index):
    strip = make_ledstrip(5)
    strip.keylist_status[index] = 1
    assert not functions.check_if_led_can_be_overwrite(
        index, strip, SimpleNamespace(adjacent_mode="RGB"))


def test_adjacent_animation_does_not_overwrite_an_active_chord():
    strip = make_ledstrip(5)
    strip.keylist = [1] * 5
    strip.keylist_status = [1] * 5
    assert not functions.check_if_led_can_be_overwrite(
        2, strip, SimpleNamespace(adjacent_mode="RGB"))


@pytest.mark.parametrize("animation", ["theaterChase", "theaterChaseRainbow"])
@pytest.mark.parametrize("count", [1, 7])
def test_chase_bounds_and_preserves_actual_target_note(monkeypatch, animation, count):
    strip = make_ledstrip(count)
    active = count - 1
    strip.keylist_status[active] = 1
    menu = SimpleNamespace(t=threading.current_thread(), is_animation_running=True,
                           is_idle_animation_running=False)
    settings = SimpleNamespace(adjacent_mode="Off", get_backlight_color=lambda color: 255)
    monkeypatch.setattr(functions, "fastColorWipe", lambda *args: None)
    monkeypatch.setattr(functions, "calculate_brightness", lambda settings: 1)
    monkeypatch.setattr(functions.GPIO, "input", lambda pin: 1)
    sleeps = []

    def stop_after_cycle(delay):
        sleeps.append(delay)
        if len(sleeps) == 5:
            menu.is_animation_running = False

    monkeypatch.setattr(functions.time, "sleep", stop_after_cycle)
    getattr(functions, animation)(strip, settings, menu, speed_ms=1)
    assert all(index != active for index, _ in strip.strip.writes)


@pytest.mark.parametrize("animation", ["theaterChase", "theaterChaseRainbow"])
def test_chase_stops_before_drawing_another_phase(monkeypatch, animation):
    strip = make_ledstrip(10)
    menu = SimpleNamespace(t=threading.current_thread(), is_animation_running=True,
                           is_idle_animation_running=False)
    settings = SimpleNamespace(adjacent_mode="Off", get_backlight_color=lambda color: 255)
    monkeypatch.setattr(functions, "fastColorWipe", lambda *args: None)
    monkeypatch.setattr(functions, "calculate_brightness", lambda settings: 1)
    monkeypatch.setattr(functions.GPIO, "input", lambda pin: 1)

    def stop(delay):
        menu.is_animation_running = False

    monkeypatch.setattr(functions.time, "sleep", stop)
    getattr(functions, animation)(strip, settings, menu, speed_ms=1)
    assert {index for index, _ in strip.strip.writes} == {0, 5}


def test_connection_animation_preserves_pending_midi_and_interrupts_immediately(monkeypatch):
    strip = make_ledstrip(10)
    events = [object(), object(), object()]
    ports = SimpleNamespace(midi_queue=deque(events))
    settings = SimpleNamespace(adjacent_mode="Off")
    monkeypatch.setattr(functions, "fastColorWipe", lambda *args: None)
    monkeypatch.setattr(functions, "calculate_brightness", lambda settings: 1)
    sleeps = []
    monkeypatch.setattr(functions.time, "sleep", sleeps.append)
    functions.piano_connected_animation(strip, settings, ports)
    assert list(ports.midi_queue) == events
    assert not sleeps
    assert not strip.strip.writes


def test_colormap_animation_preserves_active_notes(monkeypatch):
    strip = make_ledstrip(10)
    strip.get_note_position = lambda note, settings: {21: 0, 108: 9}[note]
    strip.keylist_status[4] = 1
    menu = SimpleNamespace(t=threading.current_thread(), is_animation_running=True,
                           is_idle_animation_running=False)
    settings = SimpleNamespace(adjacent_mode="Off")
    monkeypatch.setattr(functions, "fastColorWipe", lambda *args: None)
    monkeypatch.setattr(functions, "calculate_brightness", lambda settings: 1)
    monkeypatch.setattr(functions.GPIO, "input", lambda pin: 1)
    monkeypatch.setattr(functions.cmap, "colormaps", {"test": [(255, 0, 0)] * 256})

    def stop_after_frame(delay):
        if delay == 0.01:
            menu.is_animation_running = False

    monkeypatch.setattr(functions.time, "sleep", stop_after_frame)
    functions.colormap_animation("test", strip, settings, menu)
    assert {index for index, _ in strip.strip.writes} == set(range(10)) - {4}
