import importlib
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lib.midi_queues import MidiQueues
from lib.null_drivers import Color
from lib.runtime_diagnostics import RuntimeDiagnostics


@pytest.mark.parametrize('count', [1, 2])
def test_render_waits_only_after_consuming_pending_activity(monkeypatch, count):
    # Only hardware/OS boundaries are replaced; exercise the production loop.
    monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'rpi_ws281x', SimpleNamespace(Color=Color))
    VisualizerApp = importlib.import_module('visualizer').VisualizerApp
    app = VisualizerApp.__new__(VisualizerApp)
    app.stop_event = threading.Event()
    queues = MidiQueues()
    waits = []

    class ObservedEvent(threading.Event):
        def wait(self, timeout=None):
            waits.append((len(queues.live_visualizer_queue), self.is_set()))
            app.stop_event.set()
            return self.is_set()

    queues.activity = ObservedEvent()
    for _ in range(count):
        queues.enqueue_live('note')
    ports = SimpleNamespace(queues=queues, midipending=queues.live_visualizer_queue,
                            refresh_queue_diagnostics=Mock())
    strip = SimpleNamespace(strip=Mock(), current_fps=0)
    app.ci = SimpleNamespace(platform=None, ledstrip=strip, midiports=ports,
                             saving=SimpleNamespace(start_time=time.perf_counter(), is_playing_midi=False),
                             learning=SimpleNamespace(is_started_midi=False),
                             menu=SimpleNamespace(), ledsettings=None, usersettings=None, hotspot=None)
    app.state_manager = Mock()
    app.state_manager.is_active_use.return_value = True
    app.state_manager.get_loop_delay.return_value = .002
    app.runtime_diagnostics = RuntimeDiagnostics()
    app.event_loop_stamp = app.last_frame_time = time.perf_counter()
    app._housekeeping_loop = lambda: None
    app.check_activity_backlight = app.check_color_mode = lambda *args: None
    app.update_fps_stats = lambda: None
    app.led_effects_processor = Mock()
    app.led_effects_processor.process_fade_effects.return_value = False

    def process_slice():
        # Simulate a bounded slice leaving work for the next frame.
        queues.pop_queue(ports.midipending)
        return True

    app.midi_event_processor = SimpleNamespace(last_sustain=0, process_midi_events=process_slice)
    app.run()
    app._housekeeping_thread.join(1)
    assert not queues.live_visualizer_queue, 'loop slept with pending MIDI'
    assert waits == [(0, False)], 'consumed activity caused a redundant render iteration'
