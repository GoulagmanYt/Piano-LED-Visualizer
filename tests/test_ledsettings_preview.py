from types import SimpleNamespace
from unittest.mock import Mock

from lib.ledsettings import LedSettings


def test_range_preview_uses_calibrated_mapping_and_publishes_frame(monkeypatch):
    from lib import ledsettings

    strip = Mock()
    strip.numPixels.return_value = 8
    mapping = Mock(side_effect=lambda note, settings: {21: 6, 108: 1}[note])
    settings = LedSettings.__new__(LedSettings)
    settings.ledstrip = SimpleNamespace(strip=strip, get_note_position=mapping)
    settings.multicolor = [[10, 20, 30]]
    settings.multicolor_range = [[21, 108]]
    monkeypatch.setattr(ledsettings, "fastColorWipe", Mock())
    settings.light_keys_in_range("Key_range1")
    assert [call.args[0] for call in strip.setPixelColor.call_args_list] == [6, 1]
    assert [call.args[0] for call in mapping.call_args_list] == [21, 108]
    strip.show.assert_called_once_with()


def test_range_preview_on_empty_strip_does_not_write_pixels(monkeypatch):
    from lib import ledsettings

    strip = Mock()
    strip.numPixels.return_value = 0
    settings = LedSettings.__new__(LedSettings)
    settings.ledstrip = SimpleNamespace(strip=strip)
    settings.multicolor = [[10, 20, 30]]
    settings.multicolor_range = [[21, 108]]
    monkeypatch.setattr(ledsettings, "fastColorWipe", Mock())
    settings.light_keys_in_range("Key_range1")
    strip.setPixelColor.assert_not_called()
