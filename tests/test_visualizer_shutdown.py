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
