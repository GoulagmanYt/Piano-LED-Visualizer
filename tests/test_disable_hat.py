import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

from lib.null_drivers import GPIOnull


def test_disabled_hat_never_loads_gpio_and_disables_spi(tmp_path, monkeypatch):
    # Load independent driver modules against an isolated config, without
    # changing the already-imported drivers used by the rest of the suite.
    import lib.rpi_drivers as drivers
    import xml.etree.ElementTree as ET
    original_parse = ET.parse
    config = tmp_path / 'settings.xml'
    config.write_text('<settings><disable_hat>1</disable_hat></settings>')
    monkeypatch.setattr(ET, 'parse', lambda path: original_parse(config))
    real_import = drivers.importlib.import_module
    calls = []
    def fake_import(name):
        calls.append(name)
        if name == 'spidev':
            return Mock()
        if name == 'rpi_ws281x':
            raise ModuleNotFoundError(name)
        return real_import(name)
    monkeypatch.setattr(drivers.importlib, 'import_module', fake_import)
    spec = importlib.util.spec_from_file_location('isolated_drivers', Path(drivers.__file__))
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    assert isolated.HAT_DISABLED
    assert isinstance(isolated.GPIO, GPIOnull)
    assert 'RPi.GPIO' not in calls and 'rpi_lgpio.RPi.GPIO' not in calls
    assert isolated.GPIO.input(12) == 1
    assert isolated.GPIO.input(20) == 1
    monkeypatch.setitem(sys.modules, 'lib.rpi_drivers', isolated)
    import lib.LCD_Config as lcd
    spec = importlib.util.spec_from_file_location('isolated_lcd', Path(lcd.__file__))
    isolated_lcd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated_lcd)
    isolated.spidev.SpiDev.assert_not_called()


def test_disabled_hat_handler_does_not_process_keys(monkeypatch):
    import lib.gpio_handler as handler
    monkeypatch.setattr(handler, 'HAT_DISABLED', True)
    gpio = Mock()
    monkeypatch.setattr(handler, 'GPIO', gpio)
    instance = handler.GPIOHandler(Mock(), Mock(), Mock(), Mock(), Mock(), Mock())
    instance.process_gpio_keys()
    gpio.assert_not_called()
    gpio.setup.assert_not_called()
    gpio.input.assert_not_called()
