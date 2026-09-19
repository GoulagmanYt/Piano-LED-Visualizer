#!/usr/bin/env python3

from collections import namedtuple
import os
import unittest
from unittest.mock import MagicMock, patch
from xml.dom import minidom
from PIL import ImageFont

from lib.menulcd import MenuLCD


class TestMenuLCDRefactor(unittest.TestCase):
    def _create_mock_menu(self):
        # Create a mock instance of MenuLCD without invoking full hardware init
        menu = object.__new__(MenuLCD)
        menu.scale = lambda x: int(x)
        menu.LCD = MagicMock()
        menu.LCD.width = 128
        menu.LCD.height = 128
        menu.background_color = (0, 0, 0)
        menu.text_color = "White"
        menu.lcd_ttf = "dummy.ttf"
        default_font = ImageFont.load_default()
        menu.font = default_font
        menu._get_font_cached = MagicMock(return_value=default_font)
        menu.rotate_image = lambda img: img
        menu.screensaver_settings = {
            "time": "0",
            "date": "0",
            "cpu_chart": "0",
            "cpu": "0",
            "ram": "0",
            "temp": "0",
            "network_usage": "0",
            "sd_card_space": "1",
            "local_ip": "0",
        }
        menu.ledstrip = MagicMock()
        menu.ledstrip.led_number = 144
        menu.ledstrip.brightness_percent = 0
        menu.theme = MagicMock()
        menu.theme.title_padding = 5
        menu.theme.title_height = 15
        menu.theme.title_width_percent = 90
        menu.theme.item_gap = 5
        menu.theme.item_padding_v = 5
        menu.theme.item_padding_h = 5
        menu.theme.item_corner_radius = 15
        menu.theme.item_bg_color = (63, 63, 70)
        menu.theme.item_border_color = (63, 63, 70, 200)
        menu.theme.pointer_color = (14, 165, 233)
        menu.theme.pointer_width = 1
        menu.theme.pointer_padding = 1
        menu.theme.viewport_margin_top = 5
        menu.theme.viewport_margin_bottom = 5
        menu.theme.value_right_margin = 5
        menu.theme.value_gap = 5
        menu._get_menu_title_art = MagicMock(return_value=None)
        menu._font_height = MagicMock(return_value=12)
        menu.screen_on = 1
        menu_path = "config/menu.xml" if os.path.exists("config/menu.xml") else "../config/menu.xml"
        menu.DOMTree = minidom.parse(menu_path)
        menu.current_location = "menu"
        menu.scroll_offset = 0
        menu.pointer_position = 0
        return menu

    def test_screensaver_card_space_none_does_not_crash(self):
        menu = self._create_mock_menu()
        # Should not raise AttributeError when card_space is None
        menu.render_screensaver(
            hour="12:00",
            date="2026-09-19",
            cpu=10,
            cpu_average=10.0,
            ram=25,
            temp=45,
            card_space=None,
        )
        menu.LCD.LCD_ShowImage.assert_called_once()

    def test_screensaver_card_space_int_zero_does_not_crash(self):
        menu = self._create_mock_menu()
        # When sd_card_space was disabled, functions.py passes card_space=0
        menu.render_screensaver(
            hour="12:00",
            date="2026-09-19",
            cpu=10,
            cpu_average=10.0,
            ram=25,
            temp=45,
            card_space=0,
        )
        menu.LCD.LCD_ShowImage.assert_called_once()

    def test_screensaver_card_space_namedtuple_renders_properly(self):
        menu = self._create_mock_menu()
        DiskUsage = namedtuple("DiskUsage", ["total", "used", "free", "percent"])
        dummy_usage = DiskUsage(total=32 * 1024**3, used=8 * 1024**3, free=24 * 1024**3, percent=25.0)

        menu.render_screensaver(
            hour="12:00",
            date="2026-09-19",
            cpu=10,
            cpu_average=10.0,
            ram=25,
            temp=45,
            card_space=dummy_usage,
        )
        menu.LCD.LCD_ShowImage.assert_called_once()

    def test_brightness_zero_percent_does_not_raise_zerodivisionerror(self):
        menu = self._create_mock_menu()
        menu.current_location = "Brightness"
        menu.ledstrip.brightness_percent = 0
        menu.font = MagicMock()

        # Calling show() must not raise ZeroDivisionError
        try:
            menu.show(position="Brightness")
        except ZeroDivisionError:
            self.fail("show() raised ZeroDivisionError with brightness_percent=0")

    def test_update_ports_does_not_call_update_sequence_list(self):
        menu = self._create_mock_menu()
        menu.update_sequence_list = MagicMock()
        with patch("lib.menulcd.mido.get_input_names", return_value=["Port1"]):
            menu.update_ports()
        menu.update_sequence_list.assert_not_called()

    def test_update_sequence_list_does_not_call_update_songs(self):
        menu = self._create_mock_menu()
        menu.update_songs = MagicMock()
        with patch("lib.menulcd.minidom.parse", side_effect=Exception("skip actual file")):
            menu.update_sequence_list()
        menu.update_songs.assert_not_called()

    def test_update_multicolor_does_not_call_update_ports(self):
        menu = self._create_mock_menu()
        menu.update_ports = MagicMock()
        menu.update_multicolor([])
        menu.update_ports.assert_not_called()


if __name__ == "__main__":
    unittest.main()
