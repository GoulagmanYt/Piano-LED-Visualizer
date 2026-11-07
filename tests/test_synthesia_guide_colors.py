from types import SimpleNamespace

import mido
import pytest

import lib.color_mode as color_module
import lib.led_effects_processor as effects_module
import lib.midi_event_processor as midi_module
from lib.color_mode import Rainbow
from lib.led_effects_processor import LEDEffectsProcessor
from lib.midi_event_processor import MIDIEventProcessor


@pytest.fixture
def rainbow_scene(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(color_module.time, "time", lambda: clock[0])
    monkeypatch.setattr(color_module.cmap, "colormaps", {
        "Rainbow": [(255, 0, 0), (0, 255, 0)] * 128,
    })
    monkeypatch.setattr(color_module.cmap, "ensure_colormap_generated", lambda name: None)
    rgb = lambda red, green, blue: (int(red), int(green), int(blue))
    monkeypatch.setattr(midi_module, "Color", rgb)
    monkeypatch.setattr(midi_module, "OFF_COLOR", (0, 0, 0))
    monkeypatch.setattr(effects_module, "Color", rgb)
    pixels = {}
    ledstrip = SimpleNamespace(
        led_number=1, keylist=[0], keylist_status=[0], keylist_sustained=[0],
        keylist_color=[(0, 0, 0)], keylist_external_software=[0],
        active_pulses=[], sustain_value=0,
        strip=SimpleNamespace(setPixelColor=lambda position, color: pixels.update({position: color})),
        set_adjacent_colors=lambda *args: None,
    )
    settings = SimpleNamespace(
        mode="Normal", color_mode="Rainbow", skipped_notes="Normal",
        rainbow_offset=0, rainbow_scale=100, rainbow_timeshift=1,
        rainbow_colormap="Rainbow", fadingspeed=1000, velocity_speed=1000,
        pedal_speed=1000, fadepedal_notedrop=50, backlight_brightness=0,
        backlight_brightness_percent=0, sequence_active=False, next_step=None,
    )
    learning = SimpleNamespace(
        hand_colorL="left", hand_colorR="right",
        hand_colorList={"left": (40, 80, 120), "right": (120, 80, 40)},
    )
    menu = SimpleNamespace(screensaver_is_running=False)
    rainbow = Rainbow("Rainbow", settings)
    processor = MIDIEventProcessor(
        None, ledstrip, settings, None, SimpleNamespace(is_recording=False),
        learning, menu, rainbow,
    )
    effects = LEDEffectsProcessor(ledstrip, settings, menu, rainbow, 0, 10)
    return SimpleNamespace(
        clock=clock, pixels=pixels, ledstrip=ledstrip, settings=settings,
        processor=processor, effects=effects,
    )


@pytest.mark.parametrize("channel, expected", [(11, (40, 80, 120)), (12, (120, 80, 40))])
@pytest.mark.parametrize("mode", ["Normal", "Fading"])
def test_hand_color_survives_rainbow_frames(rainbow_scene, channel, expected, mode):
    scene = rainbow_scene
    scene.settings.mode = mode
    scene.processor.handle_note_on(mido.Message("note_on", channel=channel, velocity=1), 0, 0)
    assert scene.pixels[0] == expected

    scene.clock[0] = 1.0
    scene.effects.process_fade_effects(0.01)

    assert scene.pixels[0] == expected
    assert scene.ledstrip.keylist_color[0] == expected


@pytest.mark.parametrize("channel", [0, 1, 10])
def test_ordinary_rainbow_notes_still_animate(rainbow_scene, channel):
    scene = rainbow_scene
    scene.processor.handle_note_on(mido.Message("note_on", channel=channel), 0, 0)
    scene.effects.process_fade_effects(0)
    assert scene.pixels[0] == (255, 0, 0)

    scene.clock[0] = 1.0
    scene.effects.process_fade_effects(0)

    assert scene.pixels[0] == (0, 255, 0)
    assert scene.ledstrip.keylist_external_software[0] == 0


def test_finger_based_notes_keep_rainbow_animation(rainbow_scene):
    scene = rainbow_scene
    scene.settings.skipped_notes = "Finger-based"
    scene.processor.handle_note_on(mido.Message("note_on", channel=12), 0, 0)
    scene.clock[0] = 1.0

    scene.effects.process_fade_effects(0)

    assert scene.pixels[0] == (0, 255, 0)


@pytest.mark.parametrize("channel", [11, 12])
def test_external_release_clears_marker_and_led(rainbow_scene, channel):
    scene = rainbow_scene
    scene.processor.handle_note_on(mido.Message("note_on", channel=channel), 0, 0)

    scene.processor.handle_note_off(mido.Message("note_off", channel=channel), 1, 0)
    scene.effects.process_fade_effects(0)

    assert scene.ledstrip.keylist_external_software[0] == 0
    assert scene.ledstrip.keylist_status[0] == 0
    assert scene.pixels[0] == (0, 0, 0)


def test_ordinary_note_takes_over_a_hand_colored_led(rainbow_scene):
    scene = rainbow_scene
    scene.processor.handle_note_on(mido.Message("note_on", channel=12), 0, 0)
    scene.processor.handle_note_on(mido.Message("note_on", channel=0), 0, 0)
    scene.clock[0] = 1.0

    scene.effects.process_fade_effects(0)

    assert scene.ledstrip.keylist_external_software[0] == 0
    assert scene.pixels[0] == (0, 255, 0)
