from types import SimpleNamespace

import mido
import pytest

from lib import functions, learnmidi
from lib.async_strip import AsyncPixelStrip
from lib.ledstrip import ActiveIndexList, LedStrip
from lib.rpi_drivers import Color


class Hardware:
    def __init__(self):
        self.pixels = [0] * 8
        self.frames = []

    def numPixels(self):
        return len(self.pixels)

    def getBrightness(self):
        return 255

    def setBrightness(self, value):
        pass

    def setPixelColor(self, index, color):
        self.pixels[index] = color

    def show(self):
        self.frames.append(self.pixels.copy())

    def _cleanup(self):
        pass


@pytest.fixture
def scene(player, monkeypatch):
    settings = SimpleNamespace(adjacent_mode="Off", note_offsets=[],
                               backlight_stopped=False, backlight_brightness_percent=100,
                               get_backlight_color=lambda channel: 0)
    leds = LedStrip.__new__(LedStrip)
    leds.led_number = 8
    leds.ledsettings = settings
    leds.leds_per_meter = 72
    leds.shift = -40
    leds.reverse = False
    leds._note_position_cache_key = None
    leds._note_position_cache = {}
    leds._pulse_leds = set()
    for name in ("keylist", "keylist_status", "keylist_sustained",
                 "keylist_external_software", "keylist_guide"):
        setattr(leds, name, ActiveIndexList([0] * 8))
    leds.strip = AsyncPixelStrip(Hardware(), wait_for_dma=lambda: None)
    leds.strip.set_note_mask_provider(leds._note_mask)
    player.ledstrip = leds
    player.ledsettings = settings
    player.hand_colorR, player.hand_colorL = 0, 1
    player.prev_hand_colorR, player.prev_hand_colorL = 0, 1
    monkeypatch.setattr(learnmidi, "fastColorWipe", functions.fastColorWipe)
    monkeypatch.setattr(learnmidi, "get_note_position", functions.get_note_position)
    try:
        yield player, leds
    finally:
        leds.strip.close()


def prepare(player, messages):
    player.song_tracks = messages
    song = mido.MidiFile(ticks_per_beat=480)
    song.tracks.append(mido.MidiTrack(messages))
    player.notes_time = learnmidi.compute_notes_time(song)


def press_live(leds, note, color):
    position = leds.get_note_position(note, leds.ledsettings)
    leds.keylist_status[position] = 1
    leds.keylist[position] = 1000
    leds.strip.setPixelColor(position, color)
    leds.strip.show()


def test_real_learning_view_yields_to_live_note_and_finally_removes_its_layer(scene):
    player, leds = scene
    prepare(player, [mido.Message("note_on", channel=1, note=60, velocity=90),
                     mido.Message("note_off", channel=1, note=60, velocity=0, time=480)])
    views, frames = [], []
    live_color = Color(0, 255, 0)
    with leds.strip.animation() as animation:
        animation.fill_background(10)

        def on_scheduled(message, **kwargs):
            views.append(player._learning_strip)
            if message.type == "note_on":
                assert leds.strip.getPixels()[0] == Color(127, 0, 0)
                press_live(leds, 60, live_color)
                animation.fill_background(20)
            frames.append(leds.strip.getPixels()[0])

        player.midiports.schedule_rtp_message = on_scheduled
        player.learn_midi()
        assert frames == [live_color, live_color]
        assert player._learning_strip is None
        assert views and all(view._closed for view in views)
        assert not leds.strip._overlays
        assert leds.strip.getPixels() == [live_color] + [20] * 7


def test_learning_note_off_on_one_channel_preserves_the_other_channel(scene):
    player, leds = scene
    prepare(player, [mido.Message("note_on", channel=1, note=60, velocity=90),
                     mido.Message("note_on", channel=2, note=60, velocity=90, time=480),
                     mido.Message("note_off", channel=1, note=60, velocity=0, time=480),
                     mido.Message("note_off", channel=2, note=60, velocity=0, time=480)])
    frames = []
    player.midiports.schedule_rtp_message = lambda message, **kwargs: frames.append(leds.strip.getPixels()[0])
    with leds.strip.animation() as animation:
        animation.fill_background(10)
        player.learn_midi()
        assert frames == [Color(127, 0, 0), Color(127, 0, 0), Color(0, 0, 127), 10]
        assert leds.strip.getPixels() == [10] * 8


@pytest.mark.parametrize("termination", ["natural", "stop", "error"])
def test_learning_layer_is_released_on_every_session_exit(scene, monkeypatch, termination):
    player, leds = scene
    live_color = Color(0, 255, 0)
    press_live(leds, 62, live_color)
    views = []

    def run():
        view = player._output_strip
        views.append(view)
        view.setPixelColor(0, 55)
        view.show()
        assert leds.strip.getPixels()[0] == 55
        assert leds.strip.getPixels()[2] == live_color
        if termination == "stop":
            player.stop_learning()
        elif termination == "error":
            raise RuntimeError("learning render failure")

    monkeypatch.setattr(player, "_run_learning", run)
    with leds.strip.animation() as animation:
        animation.fill_background(10)
        player.learn_midi()
        assert not leds.strip._overlays
        assert views[0]._closed
        assert player._learning_strip is None
        assert leds.strip.getPixels() == [10, 10, live_color, 10, 10, 10, 10, 10]
        assert player.learning_state == ("error" if termination == "error" else "stopped")


def test_wrong_note_release_restores_animation_instead_of_owning_a_black_pixel(scene, monkeypatch):
    player, leds = scene
    player.show_wrong_notes = 1

    def run():
        player.handle_wrong_notes([mido.Message("note_on", note=60, velocity=90)], [], [])
        assert leds.strip.getPixels()[0] == Color(255, 0, 0)
        player.handle_wrong_notes([mido.Message("note_off", note=60, velocity=0)], [], [])
        assert leds.strip.getPixels()[0] == 10

    monkeypatch.setattr(player, "_run_learning", run)
    with leds.strip.animation() as animation:
        animation.fill_background(10)
        player.learn_midi()
        assert player.learning_state == "stopped"
