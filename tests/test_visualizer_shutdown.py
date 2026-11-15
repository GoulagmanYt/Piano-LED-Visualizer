import importlib
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lib.null_drivers import Color


@pytest.fixture
def shutdown_app(monkeypatch):
    monkeypatch.setitem(sys.modules, 'fcntl', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'rpi_ws281x', SimpleNamespace(Color=Color))
    module = importlib.import_module('visualizer')
    gpio = Mock()
    monkeypatch.setattr('lib.rpi_drivers.GPIO', gpio)
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    app = module.VisualizerApp.__new__(module.VisualizerApp)
    app._shutdown_done = False
    app.stop_event = threading.Event()
    app._housekeeping_thread = None
    app._screensaver_thread = None
    app.fh = None
    app.ci = SimpleNamespace(
        menu=SimpleNamespace(t=None),
        ledstrip=SimpleNamespace(strip=SimpleNamespace(close=Mock())),
        learning=SimpleNamespace(stop_learning=Mock(), t=None),
        playback_scheduler=SimpleNamespace(stop=Mock()),
        midiports=SimpleNamespace(close=Mock(return_value=True)),
        usersettings=SimpleNamespace(save_changes=Mock()),
    )
    return app, gpio, logger


@pytest.mark.parametrize('outcome', ['refused', 'exception', 'missing_close'])
def test_shutdown_never_cleans_gpio_while_led_dma_owner_has_not_released(shutdown_app, outcome):
    app, gpio, logger = shutdown_app
    if outcome == 'refused':
        app.ci.ledstrip.strip.close.return_value = False
    elif outcome == 'exception':
        app.ci.ledstrip.strip.close.side_effect = RuntimeError('DMA worker still active')
    else:
        app.ci.ledstrip.strip = SimpleNamespace()
    app.shutdown()
    gpio.cleanup.assert_not_called()
    app.ci.midiports.close.assert_called_once()
    app.ci.usersettings.save_changes.assert_called_once()
    logger.info.assert_not_called()
    assert any('Shutdown incomplete' in call.args[0] for call in logger.warning.call_args_list)


def test_shutdown_reports_retained_midi_even_when_led_cleanup_succeeded(shutdown_app):
    app, gpio, logger = shutdown_app
    app.ci.midiports.close.return_value = False
    app.shutdown()
    gpio.cleanup.assert_called_once()
    logger.info.assert_not_called()
    assert any('MIDI' in call.args[-1] for call in logger.warning.call_args_list)


def test_shutdown_reports_release_only_after_all_cleanups_succeed(shutdown_app):
    app, gpio, logger = shutdown_app
    app.shutdown()
    gpio.cleanup.assert_called_once()
    logger.info.assert_called_once_with('Shutdown complete: LEDs black, DMA and MIDI released')
    logger.warning.assert_not_called()


@pytest.mark.parametrize('midi,fade,pending,expected_wait', [
    (0, True, False, .008), (1, True, False, .002),
    (0, False, False, .025), (0, True, True, None),
])
def test_run_paces_pure_fades_but_drains_midi_without_delay(
        shutdown_app, monkeypatch, midi, fade, pending, expected_wait):
    import gc

    app, _, _ = shutdown_app
    module = sys.modules['visualizer']
    monkeypatch.setattr(gc, 'set_threshold', Mock())
    monkeypatch.setattr(module.time, 'perf_counter', lambda: 10.0)
    monkeypatch.delenv('PLV_FADE_INTERVAL_MS', raising=False)
    app.runtime_diagnostics = Mock()
    app._housekeeping_loop = Mock()
    app.event_loop_stamp = app.last_frame_time = 10.0
    app._led_frame_dirty = False
    app.ci.platform = Mock()
    app.ci.hotspot = Mock()
    app.ci.ledsettings = SimpleNamespace(mode='Fading')
    app.ci.learning.is_started_midi = False
    app.ci.saving = SimpleNamespace(is_playing_midi=False)
    app.ci.midiports = Mock()
    activity = app.ci.midiports.queues.activity
    activity.wait.side_effect = lambda timeout: app.stop_event.set()
    app.state_manager = Mock()
    app.state_manager.get_loop_delay.return_value = .002
    app.midi_event_processor = Mock()
    app.midi_event_processor.process_midi_events.return_value = midi

    def has_pending():
        if pending:
            app.stop_event.set()
        return pending

    app.midi_event_processor.has_pending_events.side_effect = has_pending
    app.led_effects_processor = Mock()
    app.led_effects_processor.process_fade_effects.return_value = fade
    app.ci.ledstrip.strip.check_health = Mock()
    app.ci.ledstrip.strip.show = Mock()
    app.check_activity_backlight = app.check_color_mode = app.update_fps_stats = Mock()
    app.run()
    app._housekeeping_thread.join(1)
    if expected_wait is None:
        activity.wait.assert_not_called()
    else:
        activity.wait.assert_called_once_with(pytest.approx(expected_wait))
    assert app.ci.ledstrip.strip.show.call_count == int(bool(midi or fade))
