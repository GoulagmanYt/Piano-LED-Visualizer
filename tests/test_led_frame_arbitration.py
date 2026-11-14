import threading
from types import SimpleNamespace

import pytest

from lib.async_strip import AsyncPixelStrip
from lib.functions import clear_ledstrip_state, fastColorWipe, rainbow
from lib.ledsettings import LedSettings
from lib.ledstrip import ActiveIndexList, LedStrip
from lib.rpi_drivers import Color


class Backend:
    def __init__(self, count=8):
        self.pixels = [0] * count
        self.frames = []
        self.condition = threading.Condition()

    def numPixels(self):
        return len(self.pixels)

    def setPixelColor(self, index, color):
        self.pixels[index] = color

    def getBrightness(self):
        return 255

    def setBrightness(self, brightness):
        pass

    def show(self):
        with self.condition:
            self.frames.append(self.pixels.copy())
            self.condition.notify_all()

    def _cleanup(self):
        pass

    def wait_for(self, frame):
        with self.condition:
            assert self.condition.wait_for(lambda: frame in self.frames, timeout=2)


@pytest.fixture
def leds():
    backend = Backend()
    ledstrip = LedStrip.__new__(LedStrip)
    ledstrip.led_number = backend.numPixels()
    ledstrip.ledsettings = SimpleNamespace(adjacent_mode="Off")
    ledstrip._pulse_leds = set()
    for name in ("keylist", "keylist_status", "keylist_sustained",
                 "keylist_external_software", "keylist_guide"):
        setattr(ledstrip, name, ActiveIndexList([0] * ledstrip.led_number))
    ledstrip.keylist_color = [(0, 0, 0)] * ledstrip.led_number
    ledstrip.strip = AsyncPixelStrip(backend, wait_for_dma=lambda: None)
    ledstrip.strip.set_note_mask_provider(ledstrip._note_mask)
    try:
        yield ledstrip, backend
    finally:
        ledstrip.strip.close()


def note(ledstrip, index, color):
    ledstrip.keylist_status[index] = 1
    ledstrip.keylist[index] = 1000
    ledstrip.strip.setPixelColor(index, color)
    ledstrip.strip.show()


def test_note_arriving_during_animation_wins_at_both_submission_boundaries(leds):
    ledstrip, backend = leds
    strip = ledstrip.strip
    with strip.animation() as animation:
        animation.fill_background(10)
        note(ledstrip, 3, 99)
        expected = [10] * 8
        expected[3] = 99
        backend.wait_for(expected)
        animation.fill_background(20)
        expected = [20] * 8
        expected[3] = 99
        backend.wait_for(expected)
    expected = [0] * 8
    expected[3] = 99
    backend.wait_for(expected)


@pytest.mark.parametrize("owner", ["keylist_status", "keylist_sustained", "keylist",
                                       "keylist_guide", "keylist_external_software"])
def test_background_and_animation_clear_preserve_each_musical_owner(leds, owner):
    ledstrip, backend = leds
    strip = ledstrip.strip
    getattr(ledstrip, owner)[2] = 1
    strip.setPixelColor(2, 99)
    strip.show()
    with strip.animation() as animation:
        animation.fill_background(40)
        strip.fill_background(5)
        assert strip.getPixels()[2] == 99
        animation.fill_background(0)
        assert strip.getPixels()[2] == 99
    expected = [5] * 8
    expected[2] = 99
    backend.wait_for(expected)


def test_sustain_release_reveals_current_animation_without_leaving_note_ghost(leds):
    ledstrip, backend = leds
    strip = ledstrip.strip
    with strip.animation() as animation:
        animation.fill_background(10)
        note(ledstrip, 2, 99)
        ledstrip.keylist_status[2] = 0
        ledstrip.keylist_sustained[2] = 1
        strip.show()
        animation.fill_background(20)
        assert strip.getPixels()[2] == 99
        ledstrip.keylist_sustained[2] = 0
        ledstrip.keylist[2] = 0
        strip.setPixelColor(2, 0)
        strip.show()
        backend.wait_for([20] * 8)


def test_adjacent_pixels_and_pulse_wings_share_note_priority(leds):
    ledstrip, _ = leds
    strip = ledstrip.strip
    ledstrip.ledsettings.adjacent_mode = "Same"
    ledstrip.keylist_status[3] = 1
    ledstrip._pulse_leds = {6}
    for index in (2, 3, 4, 5, 6, 7):
        strip.setPixelColor(index, 99)
    strip.show()
    with strip.animation() as animation:
        animation.fill_background(10)
        assert strip.getPixels() == [10, 10, 99, 99, 99, 99, 99, 99]


def test_retired_note_ownership_cannot_leave_a_ghost_when_animation_stops(leds):
    ledstrip, _ = leds
    strip = ledstrip.strip
    strip.fill_background(5)
    with strip.animation() as animation:
        animation.fill_background(10)
        note(ledstrip, 2, 99)
        ledstrip.keylist_status[2] = ledstrip.keylist[2] = 0
        strip.show()
    assert strip.getPixels() == [5] * 8


def test_leaving_pulse_mode_retires_wing_ownership_and_pixels(leds):
    from lib.led_effects_processor import LEDEffectsProcessor

    ledstrip, _ = leds
    strip = ledstrip.strip
    strip.fill_background(5)
    ledstrip._pulse_leds = {2}
    strip.setPixelColor(2, 99)
    strip.show()
    ledstrip.active_pulses = []
    ledstrip.ledsettings.mode = "Normal"
    ledstrip.ledsettings.fadingspeed = 1000
    processor = LEDEffectsProcessor(ledstrip, ledstrip.ledsettings,
                                    SimpleNamespace(screensaver_is_running=False),
                                    SimpleNamespace(ColorUpdate=lambda *args: None), 0, 10)
    processor.process_fade_effects(0)
    strip.show()
    assert strip.getPixels() == [5] * 8


def test_animation_does_not_publish_a_partially_prepared_note_frame(leds):
    ledstrip, backend = leds
    strip = ledstrip.strip
    staged = threading.Event()
    release = threading.Event()
    with strip.animation() as animation:
        animation.fill_background(10)

        def produce_notes():
            ledstrip.keylist_status[2] = ledstrip.keylist_status[3] = 1
            strip.setPixelColor(2, 99)
            staged.set()
            assert release.wait(2)
            strip.setPixelColor(3, 99)
            strip.show()

        producer = threading.Thread(target=produce_notes)
        producer.start()
        try:
            assert staged.wait(2)
            animation.fill_background(20)
            assert strip.getPixels() == [20] * 8
        finally:
            release.set()
            producer.join(2)
        expected = [20] * 8
        expected[2:4] = [99, 99]
        backend.wait_for(expected)
        assert all(frame[2] == frame[3] for frame in backend.frames)


def test_note_publication_cannot_publish_half_of_an_animation_frame(leds):
    ledstrip, backend = leds
    strip = ledstrip.strip
    with strip.animation() as animation:
        animation.fill_background(10)
        for index in range(4):
            animation.setPixelColor(index, 20)
        note(ledstrip, 6, 99)
        expected = [10] * 8
        expected[6] = 99
        backend.wait_for(expected)
        assert strip.getPixels() == expected
        for index in range(4, 8):
            animation.setPixelColor(index, 20)
        animation.show()
        expected = [20] * 8
        expected[6] = 99
        backend.wait_for(expected)


def test_stale_animation_cannot_clear_or_publish_over_its_replacement(leds):
    ledstrip, _ = leds
    strip = ledstrip.strip
    old = strip.animation()
    old.fill_background(10)
    with strip.animation() as current:
        current.fill_background(20)
        old.fill_background(30)
        old.close()
        assert strip.getPixels() == [20] * 8


def test_learning_layer_supports_explicit_black_and_transparency_below_live_notes(leds):
    ledstrip, _ = leds
    strip = ledstrip.strip
    with strip.animation() as animation, strip.priority_view() as guide:
        animation.fill_background(10)
        guide.setPixelColor(1, 0)
        guide.setPixelColor(2, 55)
        guide.show()
        assert strip.getPixels()[1:3] == [0, 55]
        note(ledstrip, 2, 99)
        guide.fill_background(7)
        assert strip.getPixels()[1:3] == [10, 99]
        guide.setPixelColor(1, 55)
        guide.show()
        guide.clearPixel(1)
        guide.show()
        assert strip.getPixels()[1:3] == [10, 99]


def test_live_note_release_reveals_guide_then_current_animation(leds):
    ledstrip, _ = leds
    strip = ledstrip.strip
    with strip.animation() as animation, strip.priority_view() as guide:
        animation.fill_background(10)
        guide.setPixelColor(2, 55)
        guide.show()
        note(ledstrip, 2, 99)
        ledstrip.keylist_status[2] = 0
        ledstrip.keylist[2] = 0
        strip.setPixelColor(2, 0)
        strip.show()
        assert strip.getPixels()[2] == 55
        guide.close()
        assert strip.getPixels()[2] == 10


def test_unbound_adapter_treats_explicit_writes_as_foreground_including_black():
    strip = AsyncPixelStrip(Backend(), wait_for_dma=lambda: None)
    try:
        with strip.animation() as animation:
            animation.fill_background(10)
            strip.setPixelColor(2, 99)
            strip.setPixelColor(3, 0)
            strip.show()
            animation.fill_background(20)
            assert strip.getPixels() == [20, 20, 99, 0, 20, 20, 20, 20]
    finally:
        strip.close()


def test_fast_color_wipe_is_a_background_operation_and_blackout_is_explicit(leds):
    ledstrip, backend = leds
    strip = ledstrip.strip
    note(ledstrip, 3, 99)
    settings = SimpleNamespace(backlight_stopped=False, backlight_brightness_percent=100,
                               get_backlight_color=lambda channel: 5)
    fastColorWipe(strip, True, settings)
    expected = [Color(5, 5, 5)] * 8
    expected[3] = 99
    backend.wait_for(expected)
    with strip.animation() as animation:
        animation.fill_background(10)
        clear_ledstrip_state(ledstrip)
        animation.show()
        backend.wait_for([0] * 8)
        assert strip.getPixels() == [0] * 8


def test_animation_wrapper_releases_its_layer_even_after_failure(leds, monkeypatch):
    from lib import functions

    ledstrip, backend = leds
    note(ledstrip, 3, 99)
    menu = SimpleNamespace(t=threading.current_thread(), is_animation_running=True,
                           is_idle_animation_running=False)
    settings = SimpleNamespace(backlight_stopped=True, adjacent_mode="Off",
                               get_backlight_color=lambda channel: 0)
    monkeypatch.setattr(functions, "calculate_brightness", lambda settings: 1)
    monkeypatch.setattr(functions.GPIO, "input", lambda pin: 1)

    def fail(delay):
        raise RuntimeError("animation failed")

    monkeypatch.setattr(functions.time, "sleep", fail)
    with pytest.raises(RuntimeError, match="animation failed"):
        rainbow(ledstrip, settings, menu, speed_ms=1)
    expected = [0] * 8
    expected[3] = 99
    backend.wait_for(expected)
    assert ledstrip.strip._animation is None


def preview_settings(ledstrip):
    settings = LedSettings.__new__(LedSettings)
    settings._mode = "Normal"
    settings.ledstrip = ledstrip
    settings.menu = SimpleNamespace(is_animation_running=False, is_idle_animation_running=False)
    settings._range_preview = None
    settings._range_preview_source = None
    settings.multicolor = [[10, 20, 30]]
    settings.multicolor_range = [[60, 67]]
    settings.note_offsets = []
    settings.adjacent_mode = "Off"
    settings.backlight_stopped = False
    settings.backlight_brightness_percent = 100
    settings.backlight_red, settings.backlight_green, settings.backlight_blue = 1, 2, 3
    ledstrip.ledsettings = settings
    ledstrip.leds_per_meter = 72
    ledstrip.shift = -40
    ledstrip.reverse = False
    ledstrip._note_position_cache_key = None
    ledstrip._note_position_cache = {}
    return settings


def test_lcd_preview_persists_between_edits_but_never_overwrites_live_notes(leds):
    ledstrip, _ = leds
    settings = preview_settings(ledstrip)
    strip = ledstrip.strip
    with strip.animation() as animation:
        animation.fill_background(10)
        note(ledstrip, 0, 99)
        settings.light_keys_in_range("Key_range1")
        view = settings._range_preview
        assert strip.getPixels()[0] == 99
        assert strip.getPixels()[7] == Color(10, 20, 30)
        note(ledstrip, 7, 88)
        settings.multicolor_range = [[61, 66]]
        settings.light_keys_in_range("Key_range1")
        assert settings._range_preview is view
        assert strip.getPixels() == [99, Color(10, 20, 30), 10, 10, 10, 10, Color(10, 20, 30), 88]
        settings.close_range_preview()
        assert strip.getPixels() == [99, 10, 10, 10, 10, 10, 10, 88]
        assert not strip._overlays


@pytest.mark.parametrize("destination,remaining", [("menu", False), ("Multicolor", False),
                                                   ("Key_range2", True), ("default", True)])
def test_lcd_navigation_releases_preview_only_when_leaving_range_editor(leds, destination, remaining):
    from lib.menulcd import MenuLCD

    ledstrip, _ = leds
    settings = preview_settings(ledstrip)
    settings.light_keys_in_range("Key_range1")
    menu = MenuLCD.__new__(MenuLCD)
    menu.current_location = "Key_range1"
    menu.ledsettings = settings
    menu._lcd_lock = threading.RLock()
    menu._show_locked = lambda *args: True  # LCD drawing is the external boundary.
    menu.show(destination)
    assert (settings._range_preview is not None) is remaining
    settings.close_range_preview()


@pytest.mark.parametrize("action", ["back", "screen_off"])
def test_lcd_back_and_screen_off_release_preview(leds, action):
    from unittest.mock import Mock

    from lib.menulcd import MenuLCD

    ledstrip, _ = leds
    settings = preview_settings(ledstrip)
    settings.light_keys_in_range("Key_range1")
    menu = MenuLCD.__new__(MenuLCD)
    menu.current_location = "Key_range1"
    menu.ledsettings = settings
    menu.parent_menu = "data"
    menu.usersettings = Mock()
    if action == "back":
        menu.go_back()
    else:
        menu.disable_screen()
    assert settings._range_preview is None
    assert not ledstrip.strip._overlays


def test_disabled_clears_state_once_and_rejects_old_and_new_producers(leds):
    ledstrip, backend = leds
    settings = preview_settings(ledstrip)
    strip = ledstrip.strip
    note(ledstrip, 2, 99)
    initial = [0] * 8
    initial[2] = 99
    backend.wait_for(initial)
    settings.light_keys_in_range("Key_range1")
    old_preview = settings._range_preview
    old_animation = strip.animation()
    old_animation.fill_background(10)
    rendered = [10] * 8
    rendered[0] = rendered[7] = Color(10, 20, 30)
    rendered[2] = 99
    backend.wait_for(rendered)
    strip.setPixelColor(3, 88)  # Staged before Disabled, never committed.
    ledstrip.active_pulses = [object()]
    with backend.condition:
        backend.frames.clear()
    settings.mode = "Disabled"
    backend.wait_for([0] * 8)
    for states in (ledstrip.keylist, ledstrip.keylist_status, ledstrip.keylist_sustained,
                   ledstrip.keylist_guide, ledstrip.keylist_external_software):
        assert states == [0] * 8
    assert ledstrip.active_pulses == []
    assert settings._range_preview is None
    old_preview.show()
    old_animation.show()
    strip.setPixelColor(0, 66)
    strip.show()
    strip.fill_background(77)
    with strip.priority_view() as new_guide, strip.animation() as new_animation:
        new_guide.setPixelColor(0, 55)
        new_guide.show()
        new_animation.fill_background(44)
    settings.mode = "Disabled"  # Idempotent: no extra hardware clear.
    assert strip.getPixels() == [0] * 8
    assert backend.frames == [[0] * 8]
    old_animation.close()


def test_reenable_invalidates_views_created_while_disabled_and_accepts_new_notes(leds):
    ledstrip, _ = leds
    settings = preview_settings(ledstrip)
    strip = ledstrip.strip
    settings.mode = "Disabled"
    stale = strip.priority_view()
    stale.setPixelColor(0, 99)
    settings.mode = "Normal"
    expected = [Color(1, 2, 3)] * 8
    stale.show()
    stale.close()
    assert strip.getPixels() == expected
    note(ledstrip, 2, 88)
    expected[2] = 88
    assert strip.getPixels() == expected


def test_initial_disabled_setting_is_applied_when_hardware_is_bound(leds):
    from unittest.mock import Mock

    ledstrip, _ = leds
    settings = preview_settings(ledstrip)
    settings.ledstrip = None
    settings.mode = "Disabled"
    note(ledstrip, 2, 99)
    settings.add_instance(Mock(), ledstrip)
    assert ledstrip.strip.getPixels() == [0] * 8
    assert not ledstrip.strip._output_enabled


def test_disabled_sequence_uses_the_same_state_reset_and_output_latch(leds, tmp_path, monkeypatch):
    ledstrip, _ = leds
    settings = preview_settings(ledstrip)
    note(ledstrip, 2, 99)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "sequences.xml").write_text(
        "<sequences><sequence_1><next_step>0</next_step><control_number>64</control_number>"
        "<step_1><color>Single</color><light_mode>Disabled</light_mode>"
        "<Red>1</Red><Green>2</Green><Blue>3</Blue></step_1></sequence_1></sequences>"
    )
    settings.set_sequence(0, 0)
    assert settings.incoming_setting_change
    assert settings.mode == "Disabled"
    assert ledstrip.keylist_status == [0] * 8
    assert ledstrip.strip.getPixels() == [0] * 8
    assert not ledstrip.strip._output_enabled


def test_hardware_close_still_latches_black_when_output_is_disabled(leds):
    ledstrip, backend = leds
    ledstrip.strip.set_output_enabled(False)
    ledstrip.strip.close()
    assert backend.frames[-1] == [0] * 8
    assert ledstrip.strip.getPixels() == [0] * 8


def test_web_observer_reads_composed_frame_without_other_producers_staging(leds):
    ledstrip, _ = leds
    strip = ledstrip.strip
    observations = []

    def observe():
        observations.append((strip.getPixels(), strip.getPixelColor(2)))

    with strip.animation() as animation:
        animation.fill_background(10)
        note(ledstrip, 2, 99)
        strip.setPixelColor(2, 88)  # Producer-local, deliberately uncommitted.
        animation.setPixelColor(4, 22)
        assert strip.getPixelColor(2) == 88
        assert animation.getPixelColor(4) == 22
        assert animation.getPixels()[4] == 22
        reader = threading.Thread(target=observe, name="fake-web-led-emulator")
        reader.start()
        reader.join(2)
        assert not reader.is_alive()
        expected = [10] * 8
        expected[2] = 99
        assert observations == [(expected, 99)]
        animation.show()
        reader = threading.Thread(target=observe, name="fake-web-led-emulator")
        reader.start()
        reader.join(2)
        assert not reader.is_alive()
        expected = expected.copy()
        expected[4] = 22
        assert observations[-1] == (expected, 99)


def test_disabled_observer_cannot_see_old_staging_or_a_reopened_view(leds):
    ledstrip, _ = leds
    settings = preview_settings(ledstrip)
    strip = ledstrip.strip
    strip.setPixelColor(2, 99)
    settings.mode = "Disabled"
    with strip.priority_view() as guide:
        guide.setPixelColor(2, 77)
        guide.show()
        observations = []

        def observe():
            observations.append((strip.getPixels(), strip.getPixelColor(2)))

        reader = threading.Thread(target=observe, name="fake-web-led-emulator")
        reader.start()
        reader.join(2)
        assert not reader.is_alive()
        assert observations == [([0] * 8, 0)]
        assert strip.getPixels() == [0] * 8
