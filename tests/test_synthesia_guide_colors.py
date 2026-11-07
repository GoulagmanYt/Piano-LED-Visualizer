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


@pytest.mark.parametrize('channel,expected', [(1, (40, 80, 120)), (5, (40, 80, 120)),
                                             (6, (120, 80, 40)), (10, (120, 80, 40)),
                                             (11, (40, 80, 120)), (12, (120, 80, 40))])
@pytest.mark.parametrize('mode', ['Normal', 'Velocity', 'Pedal', 'Pulse', 'Fading'])
def test_explicit_guide_lights_full_brightness_until_release(rainbow_scene, mode, channel, expected):
    scene = rainbow_scene
    scene.settings.mode = mode
    scene.ledstrip.keylist_guide = [0]
    scene.processor.last_sustain = 127
    scene.ledstrip.sustain_value = 127
    scene.processor.handle_note_on(mido.Message('note_on', channel=channel, velocity=1), 0, 0, is_guide=True)
    assert scene.ledstrip.keylist_guide == [1]
    assert scene.pixels[0] == expected
    assert scene.ledstrip.keylist[0] >= 1000
    assert scene.ledstrip.active_pulses == []
    scene.clock[0] = 1.0
    scene.effects.process_fade_effects(0.1)
    assert scene.pixels[0] == expected
    assert scene.ledstrip.keylist[0] >= 1000
    # Synthesia releases guide lights on channel 0, independently of pedal.
    scene.processor.handle_note_off(mido.Message('note_off', channel=0), 1, 0)
    assert scene.ledstrip.keylist_guide == [0]
    assert scene.ledstrip.keylist_external_software == [0]
    if mode != 'Fading':
        assert scene.ledstrip.keylist == [0]
        assert scene.pixels[0] == (0, 0, 0)
    else:
        scene.effects.process_fade_effects(0.001)
        assert scene.ledstrip.keylist[0] < 1000


def test_regular_channel_one_is_not_classified_as_explicit_guide(rainbow_scene):
    scene = rainbow_scene
    scene.ledstrip.keylist_guide = [0]
    scene.processor.handle_note_on(mido.Message('note_on', channel=1, velocity=1), 0, 0)
    assert scene.ledstrip.keylist_guide == [0]
    assert scene.ledstrip.keylist_external_software == [0]


def test_guides_are_not_recorded_as_performance(rainbow_scene):
    from unittest.mock import Mock
    scene = rainbow_scene
    scene.ledstrip.keylist_guide = [0]
    scene.settings.mode = 'Fading'
    scene.processor.saving = SimpleNamespace(is_recording=True, add_track=Mock())
    scene.processor.handle_note_on(mido.Message('note_on', channel=1, velocity=1), 0, 0, is_guide=True)
    scene.processor.handle_note_off(mido.Message('note_off', channel=0), 1, 0)
    scene.processor.saving.add_track.assert_not_called()


def make_guide_queue_scene(scene, monkeypatch):
    from lib.midi_queues import MidiQueues
    queues = MidiQueues()
    scene.ledstrip.keylist_guide = [0]
    scene.ledstrip.get_note_position = lambda note, settings: 0
    scene.processor.midiports = SimpleNamespace(queues=queues)
    scene.processor.saving.is_playing_midi = False
    scene.processor.learning.is_started_midi = False
    monkeypatch.setattr(midi_module.app_state, 'practice_active', False, raising=False)
    return queues


def test_source_aware_guide_lane_renders_and_clears(rainbow_scene, monkeypatch):
    scene = rainbow_scene
    queues = make_guide_queue_scene(scene, monkeypatch)
    queues.enqueue_guide(mido.Message('note_on', note=60, channel=6, velocity=1), timestamp=1)
    assert scene.processor.process_guide_events()
    assert scene.pixels[0] == (120, 80, 40)
    assert scene.ledstrip.keylist_guide == [1]
    assert queues.activity.is_set()
    queues.enqueue_guide(mido.Message('note_off', note=60, channel=0), timestamp=2)
    assert scene.processor.process_guide_events()
    assert scene.ledstrip.keylist_guide == [0]
    assert scene.pixels[0] == (0, 0, 0)


def test_reset_clears_guides_without_erasing_regular_notes(rainbow_scene, monkeypatch):
    scene = rainbow_scene
    queues = make_guide_queue_scene(scene, monkeypatch)
    scene.processor.handle_note_on(mido.Message('note_on', channel=0, velocity=100), 0, 0)
    queues.enqueue_guide(None)
    scene.processor.process_guide_events()
    assert scene.ledstrip.keylist_status == [1]
    assert scene.ledstrip.keylist[0] > 0


@pytest.mark.parametrize('owner', ['playback', 'learning', 'practice'])
def test_local_modes_clear_guide_and_do_not_replay_stale_events(rainbow_scene, monkeypatch, owner):
    scene = rainbow_scene
    queues = make_guide_queue_scene(scene, monkeypatch)
    note = mido.Message('note_on', note=60, channel=1, velocity=1)
    queues.enqueue_guide(note)
    scene.processor.process_guide_events()
    queues.enqueue_guide(note)
    if owner == 'playback':
        scene.processor.saving.is_playing_midi = True
    elif owner == 'learning':
        scene.processor.learning.is_started_midi = True
    else:
        monkeypatch.setattr(midi_module.app_state, 'practice_active', True)
    assert scene.processor.process_guide_events()
    assert scene.ledstrip.keylist_guide == [0]
    assert not queues.guide_queue
    assert scene.pixels[0] == (0, 0, 0)


def test_unmatched_guide_off_does_not_turn_off_ordinary_note(rainbow_scene, monkeypatch):
    scene = rainbow_scene
    queues = make_guide_queue_scene(scene, monkeypatch)
    scene.processor.handle_note_on(mido.Message('note_on', channel=0, velocity=100), 0, 0)
    queues.enqueue_guide(mido.Message('note_off', note=60, channel=0))
    scene.processor.process_guide_events()
    assert scene.ledstrip.keylist_status == [1]
    assert scene.ledstrip.keylist[0] > 0


def test_session_routes_computer_guide_through_queue_to_renderer(rainbow_scene, monkeypatch):
    from lib.learning_session import LearningSession
    scene = rainbow_scene
    queues = make_guide_queue_scene(scene, monkeypatch)
    piano = []
    computer = []
    session = LearningSession(
        guide_sink=queues.enqueue_guide,
        piano_sink=lambda msg, ts: piano.append(msg),
        computer_sink=lambda msg, ts: computer.append(msg),
    )
    session.route_computer(mido.Message('note_on', note=60, channel=1, velocity=1))
    assert scene.processor.process_guide_events()
    assert scene.pixels[0] == (40, 80, 120)
    assert piano == [] and computer == []
    session.route_piano(mido.Message('note_on', note=60, velocity=80))
    session.route_computer(mido.Message('note_on', note=60, velocity=80))
    assert len(computer) == 1 and piano == []
    session.close()
    scene.processor.process_guide_events()
    assert scene.ledstrip.keylist_guide == [0]
    assert scene.pixels[0] == (0, 0, 0)


def test_learning_piano_events_feed_recording_without_modifying_guides(rainbow_scene, monkeypatch):
    from unittest.mock import Mock
    scene = rainbow_scene
    queues = make_guide_queue_scene(scene, monkeypatch)
    scene.processor.saving.is_recording = True
    scene.processor.saving.add_track = Mock()
    scene.processor.handle_note_on(mido.Message('note_on', note=60, channel=1, velocity=1), 0, 0, is_guide=True)
    queues.enqueue_learning_piano(mido.Message('note_on', note=60, velocity=100), 2)
    queues.enqueue_learning_piano(mido.Message('note_on', note=60, velocity=0), 3)
    assert scene.processor.process_learning_piano_events()
    assert scene.processor.saving.add_track.call_args_list[0].args == ('note_on', 60, 100, 2)
    assert scene.processor.saving.add_track.call_args_list[1].args == ('note_off', 60, 0, 3)
    assert scene.ledstrip.keylist_guide == [1]
    assert scene.pixels[0] == (40, 80, 120)
